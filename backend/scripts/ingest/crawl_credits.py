#!/usr/bin/env python3
"""
TMDb Async Credits Crawler (Phase 1 Ticket 3)

Crawls `/movie/{id}/credits` for all qualifying movie IDs and writes cast edges to GCS.
- AsyncTokenBucket + Semaphore for rate limiting (35 req/s, 20 concurrent).
- Filters cast to `known_for_department == "Acting"`.
- Output JSONL shape: {movie_id, person_id, character, order}.
- Checkpoint/resume: downloads checkpoint from GCS on start, uploads every 1000 completions.
- On completion: uploads credits_crawl.jsonl + checkpoint to GCS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm.asyncio import tqdm

import utils.gcs as gcs
from settings import settings

logger = logging.getLogger(__name__)

CREDITS_BLOB = "pipeline/credits_crawl.jsonl"
CHECKPOINT_BLOB = "pipeline/credits_crawl_checkpoint.txt"

MAX_REQUESTS_PER_SECOND = 35
CONCURRENT_CONNECTIONS = 20
CHECKPOINT_INTERVAL = 1000


class _RateLimitError(Exception):
    pass


class AsyncTokenBucket:
    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self.tokens) / self.rate)


def _make_headers() -> tuple[dict, dict]:
    if settings.tmdb_api_read_token:
        return {"accept": "application/json", "Authorization": f"Bearer {settings.tmdb_api_read_token}"}, {}
    return {"accept": "application/json"}, {"api_key": settings.tmdb_api_key}


async def _fetch_credits(
    client: httpx.AsyncClient,
    movie_id: int,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
) -> httpx.Response:
    headers, params = _make_headers()
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"

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


async def _crawl_one(
    client: httpx.AsyncClient,
    movie_id: int,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
    output_fd,
) -> bool:
    try:
        response = await _fetch_credits(client, movie_id, limiter, sem)
        if response.status_code == 404:
            return True
        if response.status_code != 200:
            logger.warning("Movie %d: unexpected status %d", movie_id, response.status_code)
            return False
        for member in response.json().get("cast", []):
            if member.get("known_for_department") == "Acting":
                output_fd.write(json.dumps({
                    "movie_id": movie_id,
                    "person_id": member["id"],
                    "character": member.get("character", ""),
                    "order": member.get("order", 0),
                }) + "\n")
        output_fd.flush()
        return True
    except Exception:
        logger.exception("Failed to crawl movie %d", movie_id)
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
            # TMDB movie IDs are stable permanent integers from TMDB's own export — safe checkpoint keys.
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
        with tqdm(total=len(remaining), desc="Crawling credits", unit="movie") as pbar:
            for i in range(0, len(remaining), chunk_size):
                chunk = remaining[i : i + chunk_size]
                async with httpx.AsyncClient() as client:
                    results = await asyncio.gather(*[
                        _crawl_one(client, mid, limiter, sem, output_fd)
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
    logger.info("=== TMDb Credits Crawler ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        movies_path = tmpdir_path / "movies.json"
        output_path = tmpdir_path / "credits_crawl.jsonl"
        checkpoint_path = tmpdir_path / "checkpoint.txt"

        logger.info("Downloading movie list from GCS: %s", movies_blob)
        if not gcs.download_to_file(movies_blob, movies_path):
            raise RuntimeError(f"GCS blob not found: {movies_blob}. Run download_movie_ids first.")

        with open(movies_path) as f:
            movie_ids = [m["id"] for m in json.load(f)]

        if not force:
            gcs.download_to_file(CHECKPOINT_BLOB, checkpoint_path)
            if gcs.blob_exists(CREDITS_BLOB):
                gcs.download_to_file(CREDITS_BLOB, output_path)

        asyncio.run(_crawl_async(movie_ids, output_path, checkpoint_path))

        logger.info("Uploading credits to GCS: %s", CREDITS_BLOB)
        gcs.upload_from_file(output_path, CREDITS_BLOB)
        gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)
        logger.info("Credits crawl complete.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Crawl TMDB movie credits to GCS.")
    parser.add_argument("--movies-blob", default="pipeline/movie_ids_to_crawl.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(movies_blob=args.movies_blob, force=args.force)


if __name__ == "__main__":
    main()
