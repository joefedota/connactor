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
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

from ingest import gcs

CREDITS_BLOB = "pipeline/credits_crawl.jsonl"
CHECKPOINT_BLOB = "pipeline/credits_crawl_checkpoint.txt"

MAX_REQUESTS_PER_SECOND = 35
CONCURRENT_CONNECTIONS = 20
CHECKPOINT_INTERVAL = 1000


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
                sleep_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(sleep_time)


def _get_api_credentials() -> tuple[str | None, str | None]:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
    api_key = os.getenv("TMDB_API_KEY")
    bearer_token = os.getenv("TMDB_API_READ_TOKEN")
    return api_key, bearer_token


async def _crawl_one(
    client: httpx.AsyncClient,
    movie_id: int,
    api_key: str | None,
    bearer_token: str | None,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
    output_fd,
) -> bool:
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"
    headers = {"accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
        params: dict = {}
    else:
        params = {"api_key": api_key}

    await sem.acquire()
    try:
        await limiter.acquire()
        response = await client.get(url, headers=headers, params=params, timeout=10.0)

        if response.status_code in (424, 429):
            retry_after = int(response.headers.get("Retry-After", 2))
            print(f"\n  [RATE LIMIT] Status {response.status_code}. Sleeping {retry_after}s...")
            await asyncio.sleep(retry_after)
            await limiter.acquire()
            response = await client.get(url, headers=headers, params=params, timeout=10.0)

        if response.status_code == 404:
            return True  # movie removed — skip and checkpoint

        if response.status_code != 200:
            print(f"\n  [ERROR] Movie {movie_id} status {response.status_code}")
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

    except Exception as e:
        print(f"\n  [EXCEPTION] Movie {movie_id}: {e}")
        return False
    finally:
        sem.release()


async def _crawl_async(
    movie_ids: list[int],
    api_key: str | None,
    bearer_token: str | None,
    output_path: Path,
    checkpoint_path: Path,
) -> None:
    limiter = AsyncTokenBucket(MAX_REQUESTS_PER_SECOND, MAX_REQUESTS_PER_SECOND)
    sem = asyncio.Semaphore(CONCURRENT_CONNECTIONS)

    crawled: set[int] = set()
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            crawled = {int(line.strip()) for line in f if line.strip().isdigit()}

    remaining = [mid for mid in movie_ids if mid not in crawled]
    total = len(movie_ids)
    print(f"  Total: {total:,} | Already crawled: {len(crawled):,} | Remaining: {len(remaining):,}")

    if not remaining:
        print("  All movies already crawled.")
        return

    start_time = time.monotonic()
    completed = 0

    with open(output_path, "a", encoding="utf-8") as output_fd, \
         open(checkpoint_path, "a", encoding="utf-8") as ckpt_fd:

        chunk_size = 500
        for i in range(0, len(remaining), chunk_size):
            chunk = remaining[i : i + chunk_size]
            async with httpx.AsyncClient() as client:
                results = await asyncio.gather(*[
                    _crawl_one(client, mid, api_key, bearer_token, limiter, sem, output_fd)
                    for mid in chunk
                ])

            for mid, success in zip(chunk, results):
                if success:
                    ckpt_fd.write(f"{mid}\n")
                    crawled.add(mid)
                completed += 1

            if completed % CHECKPOINT_INTERVAL < chunk_size:
                gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)

            elapsed = time.monotonic() - start_time
            speed = completed / elapsed if elapsed > 0 else 0
            done = len(crawled)
            print(f"  Progress: {done:,}/{total:,} ({done/total*100:.1f}%) — {speed:.1f} req/s", end="\r")

    print()


def run(movies_blob: str, force: bool = False) -> None:
    print("=== TMDb Credits Crawler ===")

    api_key, bearer_token = _get_api_credentials()
    if not api_key and not bearer_token:
        raise RuntimeError("TMDB credentials not found. Set TMDB_API_READ_TOKEN in .env.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        movies_path = tmpdir_path / "movies.json"
        output_path = tmpdir_path / "credits_crawl.jsonl"
        checkpoint_path = tmpdir_path / "checkpoint.txt"

        print(f"  Downloading movie list from GCS: {movies_blob}")
        if not gcs.download_to_file(movies_blob, movies_path):
            raise RuntimeError(f"GCS blob not found: {movies_blob}. Run download_movie_ids first.")

        with open(movies_path) as f:
            movie_ids = [m["id"] for m in json.load(f)]

        if not force:
            gcs.download_to_file(CHECKPOINT_BLOB, checkpoint_path)
            if gcs.blob_exists(CREDITS_BLOB):
                gcs.download_to_file(CREDITS_BLOB, output_path)

        asyncio.run(_crawl_async(movie_ids, api_key, bearer_token, output_path, checkpoint_path))

        print(f"  Uploading credits to GCS: {CREDITS_BLOB}")
        gcs.upload_from_file(output_path, CREDITS_BLOB)
        print(f"  Uploading checkpoint to GCS: {CHECKPOINT_BLOB}")
        gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)
        print("  Credits crawl complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl TMDB movie credits to GCS.")
    parser.add_argument(
        "--movies-blob",
        default="pipeline/movie_ids_to_crawl.json",
        help="GCS blob name for the movies list.",
    )
    parser.add_argument("--force", action="store_true", help="Ignore existing checkpoint and start fresh.")
    args = parser.parse_args()
    run(movies_blob=args.movies_blob, force=args.force)


if __name__ == "__main__":
    main()
