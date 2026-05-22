#!/usr/bin/env python3
"""
TMDb Async Person Enricher (Phase 1 Ticket 5 / Issue #5)

Reads credits_crawl.jsonl from GCS, identifies actors with >= 5 credits,
then fetches /person/{id} for each to get name, popularity, profile_path, birth_year.
- AsyncTokenBucket + Semaphore for rate limiting (35 req/s, 20 concurrent).
- Output JSONL shape: {person_id, name, popularity, profile_path, birth_year}.
- Checkpoint/resume: downloads checkpoint from GCS on start, uploads every 1000 completions.
- On completion: uploads persons_crawl.jsonl + checkpoint to GCS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx
import jsonlines
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm.asyncio import tqdm

import utils.gcs as gcs
from ingest.crawl_credits import AsyncTokenBucket
from utils.settings import settings

logger = logging.getLogger(__name__)

CREDITS_BLOB = "pipeline/credits_crawl.jsonl"
PERSONS_BLOB = "pipeline/persons_crawl.jsonl"
CHECKPOINT_BLOB = "pipeline/persons_crawl_checkpoint.txt"

MIN_CREDITS = 5
MAX_REQUESTS_PER_SECOND = 35
CONCURRENT_CONNECTIONS = 20
CHECKPOINT_INTERVAL = 1000


class _RateLimitError(Exception):
    pass


def _make_headers() -> tuple[dict, dict]:
    if settings.tmdb_api_read_token:
        return {"accept": "application/json", "Authorization": f"Bearer {settings.tmdb_api_read_token}"}, {}
    return {"accept": "application/json"}, {"api_key": settings.tmdb_api_key}


async def _fetch_person(
    client: httpx.AsyncClient,
    person_id: int,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
) -> dict | None:
    headers, params = _make_headers()
    url = f"https://api.themoviedb.org/3/person/{person_id}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, _RateLimitError)),
        reraise=True,
    )
    async def _do_request() -> httpx.Response:
        await limiter.acquire()
        r = await client.get(url, headers=headers, params=params, timeout=10.0)
        if r.status_code in (429, 424):
            raise _RateLimitError(f"Rate limited on person {person_id}: {r.status_code}")
        return r

    async with sem:
        try:
            response = await _do_request()
        except Exception:
            logger.exception("Failed to fetch person %d", person_id)
            return None

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        logger.warning("Person %d: unexpected status %d", person_id, response.status_code)
        return None

    data = response.json()
    birth_year = None
    birthday = data.get("birthday")
    if birthday and len(birthday) >= 4:
        try:
            birth_year = int(birthday[:4])
        except ValueError:
            pass

    return {
        "person_id": person_id,
        "name": data.get("name", ""),
        "popularity": data.get("popularity", 0.0),
        # profile_path is a relative path e.g. "/abc123.jpg" — prepend
        # https://image.tmdb.org/t/p/w185 to get the full actor headshot URL (Phase 4).
        "profile_path": data.get("profile_path"),
        "birth_year": birth_year,
    }


async def _enrich_async(
    person_ids: list[int],
    output_path: Path,
    checkpoint_path: Path,
) -> None:
    limiter = AsyncTokenBucket(MAX_REQUESTS_PER_SECOND, MAX_REQUESTS_PER_SECOND)
    sem = asyncio.Semaphore(CONCURRENT_CONNECTIONS)

    enriched: set[int] = set()
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            enriched = {int(line.strip()) for line in f if line.strip().isdigit()}

    remaining = [pid for pid in person_ids if pid not in enriched]
    logger.info("Total persons: %d | Already enriched: %d | Remaining: %d",
                len(person_ids), len(enriched), len(remaining))

    if not remaining:
        logger.info("All persons already enriched.")
        return

    completed_since_checkpoint = 0

    with open(output_path, "a", encoding="utf-8") as output_fd, \
         open(checkpoint_path, "a", encoding="utf-8") as ckpt_fd:

        chunk_size = 500
        with tqdm(total=len(remaining), desc="Enriching persons", unit="person") as pbar:
            for i in range(0, len(remaining), chunk_size):
                chunk = remaining[i : i + chunk_size]
                async with httpx.AsyncClient() as client:
                    results = await asyncio.gather(*[
                        _fetch_person(client, pid, limiter, sem)
                        for pid in chunk
                    ])

                for pid, person in zip(chunk, results):
                    if person is not None:
                        output_fd.write(json.dumps(person) + "\n")
                    ckpt_fd.write(f"{pid}\n")
                    completed_since_checkpoint += 1
                    pbar.update(1)

                output_fd.flush()

                if completed_since_checkpoint >= CHECKPOINT_INTERVAL:
                    gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)
                    completed_since_checkpoint = 0


def run(force: bool = False) -> None:
    logger.info("=== TMDb Person Enricher ===")

    if not settings.tmdb_api_read_token and not settings.tmdb_api_key:
        raise RuntimeError("TMDB credentials not found. Set TMDB_API_READ_TOKEN in .env.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        credits_path = tmpdir_path / "credits_crawl.jsonl"
        output_path = tmpdir_path / "persons_crawl.jsonl"
        checkpoint_path = tmpdir_path / "checkpoint.txt"

        logger.info("Downloading credits from GCS: %s", CREDITS_BLOB)
        if not gcs.download_to_file(CREDITS_BLOB, credits_path):
            raise RuntimeError(f"GCS blob not found: {CREDITS_BLOB}. Run crawl_credits first.")

        logger.info("Counting person credits ...")
        counts: Counter[int] = Counter()
        with jsonlines.open(credits_path) as reader:
            for record in reader:
                counts[record["person_id"]] += 1

        qualifying = [pid for pid, cnt in counts.items() if cnt >= MIN_CREDITS]
        logger.info("Persons with >= %d credits: %d", MIN_CREDITS, len(qualifying))

        if not force:
            gcs.download_to_file(CHECKPOINT_BLOB, checkpoint_path)
            if gcs.blob_exists(PERSONS_BLOB):
                gcs.download_to_file(PERSONS_BLOB, output_path)

        asyncio.run(_enrich_async(qualifying, output_path, checkpoint_path))

        logger.info("Uploading persons to GCS: %s", PERSONS_BLOB)
        gcs.upload_from_file(output_path, PERSONS_BLOB)
        gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)
        logger.info("Person enrichment complete.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Enrich TMDB persons from credits to GCS.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()
