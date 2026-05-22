#!/usr/bin/env python3
"""
TMDb Async Delta Credits Crawler (Issue #24)

Re-crawls credits for movies that changed in TMDB since yesterday and appends
the new rows to pipeline/credits_crawl.jsonl in GCS. Designed to run daily as
a Cloud Run Job triggered by Cloud Scheduler.

Flow:
  1. Page through /movie/changes?start_date=yesterday → list of changed movie IDs
  2. For each: GET /movie/{id}/credits, extract Acting-department cast
  3. Download existing credits_crawl.jsonl from GCS, append new rows, re-upload

Duplicate rows are fine — load_neo4j MERGEs on (a)-[r:APPEARED_IN]->(m) so the
node/edge set converges. We trade a slightly larger JSONL for a simpler delta.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm.asyncio import tqdm

import utils.gcs as gcs
from ingest.crawl_credits import (
    CREDITS_BLOB,
    AsyncTokenBucket,
    MAX_REQUESTS_PER_SECOND,
    CONCURRENT_CONNECTIONS,
    _crawl_one,
    _make_headers,
    _RateLimitError,
)

logger = logging.getLogger(__name__)

CHANGES_URL = "https://api.themoviedb.org/3/movie/changes"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, _RateLimitError)),
    reraise=True,
)
async def _fetch_changes_page(
    client: httpx.AsyncClient,
    start_date: str,
    end_date: str,
    page: int,
    limiter: AsyncTokenBucket,
) -> dict:
    headers, params = _make_headers()
    params = {**params, "start_date": start_date, "end_date": end_date, "page": page}
    await limiter.acquire()
    r = await client.get(CHANGES_URL, headers=headers, params=params, timeout=10.0)
    if r.status_code in (429, 424):
        raise _RateLimitError(f"Rate limited on changes page {page}")
    r.raise_for_status()
    return r.json()


async def _fetch_all_changed_ids(start_date: str, end_date: str) -> list[int]:
    limiter = AsyncTokenBucket(MAX_REQUESTS_PER_SECOND, MAX_REQUESTS_PER_SECOND)
    changed: list[int] = []
    async with httpx.AsyncClient() as client:
        first = await _fetch_changes_page(client, start_date, end_date, 1, limiter)
        total_pages = first.get("total_pages", 1)
        for entry in first.get("results", []):
            if not entry.get("adult"):
                changed.append(int(entry["id"]))
        for page in range(2, total_pages + 1):
            data = await _fetch_changes_page(client, start_date, end_date, page, limiter)
            for entry in data.get("results", []):
                if not entry.get("adult"):
                    changed.append(int(entry["id"]))
    # /movie/changes can list a movie multiple times if it changed several times in the window
    return sorted(set(changed))


async def _crawl_delta_async(movie_ids: list[int], output_path: Path) -> int:
    limiter = AsyncTokenBucket(MAX_REQUESTS_PER_SECOND, MAX_REQUESTS_PER_SECOND)
    sem = asyncio.Semaphore(CONCURRENT_CONNECTIONS)
    chunk_size = 500
    rows_before = output_path.stat().st_size if output_path.exists() else 0

    with open(output_path, "a", encoding="utf-8") as output_fd:
        with tqdm(total=len(movie_ids), desc="Delta credits", unit="movie") as pbar:
            for i in range(0, len(movie_ids), chunk_size):
                chunk = movie_ids[i : i + chunk_size]
                async with httpx.AsyncClient() as client:
                    await asyncio.gather(*[
                        _crawl_one(client, mid, limiter, sem, output_fd)
                        for mid in chunk
                    ])
                pbar.update(len(chunk))

    return output_path.stat().st_size - rows_before


def run() -> None:
    logger.info("=== TMDb Delta Credits Crawler ===")

    end_dt = datetime.now(timezone.utc).date()
    start_dt = end_dt - timedelta(days=1)
    start_date, end_date = start_dt.isoformat(), end_dt.isoformat()
    logger.info("Window: %s → %s", start_date, end_date)

    changed_ids = asyncio.run(_fetch_all_changed_ids(start_date, end_date))
    logger.info("Movies changed in window: %d", len(changed_ids))
    if not changed_ids:
        logger.info("Nothing to do.")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "credits_crawl.jsonl"

        # Append to the existing file so we keep history. load_neo4j MERGE handles dedupe.
        if gcs.blob_exists(CREDITS_BLOB):
            logger.info("Downloading existing credits to append to: %s", CREDITS_BLOB)
            gcs.download_to_file(CREDITS_BLOB, output_path)

        bytes_added = asyncio.run(_crawl_delta_async(changed_ids, output_path))
        logger.info("Appended %d bytes of new cast rows.", bytes_added)

        logger.info("Uploading merged credits to GCS: %s", CREDITS_BLOB)
        gcs.upload_from_file(output_path, CREDITS_BLOB)

    logger.info("Delta crawl complete.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    argparse.ArgumentParser(description="Crawl TMDB movie credits delta since yesterday.").parse_args()
    run()


if __name__ == "__main__":
    main()
