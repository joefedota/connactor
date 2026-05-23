#!/usr/bin/env python3
"""
TMDb Async Movie Details Crawler (Issue #29)

Crawls `/movie/{id}` for every qualifying movie ID to populate fields that aren't
in the daily ID export — vote_count, vote_average, year (from release_date),
runtime, original_language, collection_id.

Same patterns as crawl_credits.py: AsyncTokenBucket + Semaphore for rate limiting,
GCS checkpoint/resume, append-only JSONL output.

Output rows: {movie_id, vote_count, vote_average, year, runtime, original_language, collection_id}
collection_id comes from TMDB's `belongs_to_collection` (null for standalone films) and lets
the fame_rank computation collapse franchise entries (3 LOTR films → 1 effective film).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import tempfile
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm.asyncio import tqdm

import utils.gcs as gcs
from ingest.crawl_credits import (
    AsyncTokenBucket,
    CONCURRENT_CONNECTIONS,
    CHECKPOINT_INTERVAL,
    MAX_REQUESTS_PER_SECOND,
    _RateLimitError,
    _make_headers,
)
from settings import settings

logger = logging.getLogger(__name__)

DETAILS_BLOB = "pipeline/movie_details.jsonl"
CHECKPOINT_BLOB = "pipeline/movie_details_checkpoint.txt"


async def _fetch_one(
    client: httpx.AsyncClient,
    movie_id: int,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
) -> httpx.Response:
    headers, params = _make_headers()
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"

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
            raise _RateLimitError(f"Rate limited on movie {movie_id}: {r.status_code}")
        return r

    async with sem:
        return await _do_request()


def _parse_year(release_date: str | None) -> int | None:
    if not release_date or len(release_date) < 4:
        return None
    try:
        return int(release_date[:4])
    except ValueError:
        return None


async def _crawl_one_details(
    client: httpx.AsyncClient,
    movie_id: int,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
    output_fd,
) -> bool:
    try:
        response = await _fetch_one(client, movie_id, limiter, sem)
        if response.status_code == 404:
            return True
        if response.status_code != 200:
            logger.warning("Movie %d: unexpected status %d", movie_id, response.status_code)
            return False
        body = response.json()
        collection = body.get("belongs_to_collection")
        output_fd.write(json.dumps({
            "movie_id": movie_id,
            "vote_count": body.get("vote_count"),
            "vote_average": body.get("vote_average"),
            "year": _parse_year(body.get("release_date")),
            "runtime": body.get("runtime"),
            "original_language": body.get("original_language"),
            "collection_id": collection.get("id") if collection else None,
        }) + "\n")
        output_fd.flush()
        return True
    except Exception:
        logger.exception("Failed to crawl details for movie %d", movie_id)
        return False


async def _crawl_async(
    movie_ids: list[int],
    output_path: Path,
    checkpoint_path: Path,
) -> None:
    if not settings.tmdb_api_read_token and not settings.tmdb_api_key:
        raise RuntimeError("TMDB credentials not found. Set TMDB_API_READ_TOKEN in .env.")

    limiter = AsyncTokenBucket(MAX_REQUESTS_PER_SECOND, MAX_REQUESTS_PER_SECOND)
    sem = asyncio.Semaphore(CONCURRENT_CONNECTIONS)

    crawled: set[int] = set()
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            crawled = {int(line.strip()) for line in f if line.strip().isdigit()}

    remaining = [mid for mid in movie_ids if mid not in crawled]
    logger.info("Total: %d | Already crawled: %d | Remaining: %d", len(movie_ids), len(crawled), len(remaining))

    if not remaining:
        logger.info("All movies already crawled.")
        return

    completed_since_checkpoint = 0

    with open(output_path, "a", encoding="utf-8") as output_fd, \
         open(checkpoint_path, "a", encoding="utf-8") as ckpt_fd:

        chunk_size = 500
        with tqdm(total=len(remaining), desc="Crawling movie details", unit="movie") as pbar:
            for i in range(0, len(remaining), chunk_size):
                chunk = remaining[i : i + chunk_size]
                async with httpx.AsyncClient() as client:
                    results = await asyncio.gather(*[
                        _crawl_one_details(client, mid, limiter, sem, output_fd)
                        for mid in chunk
                    ])

                for mid, success in zip(chunk, results):
                    if success:
                        ckpt_fd.write(f"{mid}\n")
                    completed_since_checkpoint += 1
                    pbar.update(1)

                if completed_since_checkpoint >= CHECKPOINT_INTERVAL:
                    gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)
                    completed_since_checkpoint = 0


def run(movies_blob: str, force: bool = False) -> None:
    logger.info("=== TMDb Movie Details Crawler ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        movies_path = tmpdir_path / "movies.json"
        output_path = tmpdir_path / "movie_details.jsonl"
        checkpoint_path = tmpdir_path / "checkpoint.txt"

        logger.info("Downloading movie list from GCS: %s", movies_blob)
        if not gcs.download_to_file(movies_blob, movies_path):
            raise RuntimeError(f"GCS blob not found: {movies_blob}. Run download_movie_ids first.")

        with open(movies_path) as f:
            movie_ids = [m["id"] for m in json.load(f)]

        if not force:
            gcs.download_to_file(CHECKPOINT_BLOB, checkpoint_path)
            if gcs.blob_exists(DETAILS_BLOB):
                gcs.download_to_file(DETAILS_BLOB, output_path)

        asyncio.run(_crawl_async(movie_ids, output_path, checkpoint_path))

        logger.info("Uploading details to GCS: %s", DETAILS_BLOB)
        gcs.upload_from_file(output_path, DETAILS_BLOB)
        gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)
        logger.info("Movie details crawl complete.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Crawl TMDB movie details to GCS.")
    parser.add_argument("--movies-blob", default="pipeline/movie_ids_to_crawl.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(movies_blob=args.movies_blob, force=args.force)


if __name__ == "__main__":
    main()
