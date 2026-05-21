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
import os
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx

from ingest import gcs
from ingest.crawl_credits import AsyncTokenBucket

CREDITS_BLOB = "pipeline/credits_crawl.jsonl"
PERSONS_BLOB = "pipeline/persons_crawl.jsonl"
CHECKPOINT_BLOB = "pipeline/persons_crawl_checkpoint.txt"

MIN_CREDITS = 5
MAX_REQUESTS_PER_SECOND = 35
CONCURRENT_CONNECTIONS = 20
CHECKPOINT_INTERVAL = 1000


def _get_api_credentials() -> tuple[str | None, str | None]:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
    api_key = os.getenv("TMDB_API_KEY")
    bearer_token = os.getenv("TMDB_API_READ_TOKEN")
    return api_key, bearer_token


async def _fetch_person(
    client: httpx.AsyncClient,
    person_id: int,
    api_key: str | None,
    bearer_token: str | None,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
) -> dict | None:
    url = f"https://api.themoviedb.org/3/person/{person_id}"
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
            await asyncio.sleep(retry_after)
            await limiter.acquire()
            response = await client.get(url, headers=headers, params=params, timeout=10.0)

        if response.status_code == 404:
            return None  # person removed from TMDB

        if response.status_code != 200:
            print(f"\n  [ERROR] Person {person_id} status {response.status_code}")
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
            "profile_path": data.get("profile_path"),
            "birth_year": birth_year,
        }

    except Exception as e:
        print(f"\n  [EXCEPTION] Person {person_id}: {e}")
        return None
    finally:
        sem.release()


async def _enrich_async(
    person_ids: list[int],
    api_key: str | None,
    bearer_token: str | None,
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
    total = len(person_ids)
    print(f"  Total persons: {total:,} | Already enriched: {len(enriched):,} | Remaining: {len(remaining):,}")

    if not remaining:
        print("  All persons already enriched.")
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
                    _fetch_person(client, pid, api_key, bearer_token, limiter, sem)
                    for pid in chunk
                ])

            for pid, person in zip(chunk, results):
                if person is not None:
                    output_fd.write(json.dumps(person) + "\n")
                ckpt_fd.write(f"{pid}\n")
                enriched.add(pid)
                completed += 1

            output_fd.flush()

            if completed % CHECKPOINT_INTERVAL < chunk_size:
                gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)

            elapsed = time.monotonic() - start_time
            speed = completed / elapsed if elapsed > 0 else 0
            done = len(enriched)
            print(f"  Progress: {done:,}/{total:,} ({done/total*100:.1f}%) — {speed:.1f} req/s", end="\r")

    print()


def run(force: bool = False) -> None:
    print("=== TMDb Person Enricher ===")

    api_key, bearer_token = _get_api_credentials()
    if not api_key and not bearer_token:
        raise RuntimeError("TMDB credentials not found. Set TMDB_API_READ_TOKEN in .env.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        credits_path = tmpdir_path / "credits_crawl.jsonl"
        output_path = tmpdir_path / "persons_crawl.jsonl"
        checkpoint_path = tmpdir_path / "checkpoint.txt"

        print(f"  Downloading credits from GCS: {CREDITS_BLOB}")
        if not gcs.download_to_file(CREDITS_BLOB, credits_path):
            raise RuntimeError(f"GCS blob not found: {CREDITS_BLOB}. Run crawl_credits first.")

        print("  Counting person credits ...")
        counts: Counter[int] = Counter()
        with open(credits_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    counts[json.loads(line)["person_id"]] += 1

        qualifying = [pid for pid, cnt in counts.items() if cnt >= MIN_CREDITS]
        print(f"  Persons with >= {MIN_CREDITS} credits: {len(qualifying):,}")

        if not force:
            gcs.download_to_file(CHECKPOINT_BLOB, checkpoint_path)
            if gcs.blob_exists(PERSONS_BLOB):
                gcs.download_to_file(PERSONS_BLOB, output_path)

        asyncio.run(_enrich_async(qualifying, api_key, bearer_token, output_path, checkpoint_path))

        print(f"  Uploading persons to GCS: {PERSONS_BLOB}")
        gcs.upload_from_file(output_path, PERSONS_BLOB)
        print(f"  Uploading checkpoint to GCS: {CHECKPOINT_BLOB}")
        gcs.upload_from_file(checkpoint_path, CHECKPOINT_BLOB)
        print("  Person enrichment complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich TMDB persons from credits to GCS.")
    parser.add_argument("--force", action="store_true", help="Ignore existing checkpoint and start fresh.")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()
