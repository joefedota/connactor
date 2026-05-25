#!/usr/bin/env python3
"""
TMDb Candidate List Builder (Issue #91)

Builds the per-movie candidate list for the ingest pipeline using TMDb's
`/discover/movie` endpoint with `vote_count.gte=100`. Year-sharded so each
year-query stays under the 500-page-per-query Discover limit.

This replaces the older `download_movie_ids.py` which used the daily ID
export + a `popularity > 0.1` filter. Popularity is a daily-decaying
engagement score — bad signal for a static catalog — so we ended up either
missing catalog hits (popularity > 1.0 dropped The Internship 2013) or
exploding the candidate list (popularity > 0.1 → 518k movies).

`vote_count` is the stable "people have heard of this" signal. Querying
`/discover/movie?vote_count.gte=100` directly gives the exact ~22k movies
we want in one ~1-2 minute pass — no popularity threshold guesswork.

Output format matches the old artifact so downstream crawlers don't need
changes: list of {id, title, popularity} in `pipeline/movie_ids_to_crawl.json`.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import tempfile
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import utils.gcs as gcs
from ingest.crawl_credits import (
    AsyncTokenBucket,
    CONCURRENT_CONNECTIONS,
    MAX_REQUESTS_PER_SECOND,
    _RateLimitError,
    _make_headers,
)
from settings import settings

logger = logging.getLogger(__name__)

BLOB_NAME = "pipeline/movie_ids_to_crawl.json"
DISCOVER_URL = "https://api.themoviedb.org/3/discover/movie"
VOTE_COUNT_THRESHOLD = 100
MIN_YEAR = 1920
PAGES_PER_YEAR_LIMIT = 500  # TMDb hard cap on Discover pagination


async def _fetch_page(
    client: httpx.AsyncClient,
    year: int,
    page: int,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
) -> dict:
    headers, base_params = _make_headers()
    params = {
        **base_params,
        "vote_count.gte": VOTE_COUNT_THRESHOLD,
        "primary_release_year": year,
        "page": page,
        "include_adult": "false",
        "sort_by": "popularity.desc",
    }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, _RateLimitError)),
        reraise=True,
    )
    async def _do_request() -> dict:
        await limiter.acquire()
        r = await client.get(DISCOVER_URL, headers=headers, params=params, timeout=10.0)
        if r.status_code in (429, 424):
            raise _RateLimitError(f"Rate limited on year={year} page={page}: {r.status_code}")
        if r.status_code != 200:
            logger.warning("Discover year=%d page=%d: unexpected status %d", year, page, r.status_code)
            return {"results": [], "total_pages": 0}
        return r.json()

    async with sem:
        return await _do_request()


async def _fetch_year(
    client: httpx.AsyncClient,
    year: int,
    limiter: AsyncTokenBucket,
    sem: asyncio.Semaphore,
) -> list[dict]:
    movies: list[dict] = []
    page = 1
    first = await _fetch_page(client, year, 1, limiter, sem)
    total_pages = min(first.get("total_pages", 0), PAGES_PER_YEAR_LIMIT)
    for m in first.get("results", []):
        movies.append(m)

    if total_pages <= 1:
        return movies

    # Fetch remaining pages concurrently — semaphore + token bucket cap parallelism.
    tasks = [
        _fetch_page(client, year, p, limiter, sem)
        for p in range(2, total_pages + 1)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.exception("Failed to fetch year=%d page", year, exc_info=r)
            continue
        for m in r.get("results", []):
            movies.append(m)
    return movies


async def _build_async(end_year: int) -> list[dict]:
    if not settings.tmdb_api_read_token and not settings.tmdb_api_key:
        raise RuntimeError("TMDB credentials not found. Set TMDB_API_READ_TOKEN in .env.")

    limiter = AsyncTokenBucket(MAX_REQUESTS_PER_SECOND, MAX_REQUESTS_PER_SECOND)
    sem = asyncio.Semaphore(CONCURRENT_CONNECTIONS)

    years = list(range(MIN_YEAR, end_year + 2))  # +2 so we catch next-year movies too
    logger.info("Discover candidate list: vote_count>=%d, years %d-%d (%d years)",
                VOTE_COUNT_THRESHOLD, years[0], years[-1], len(years))

    seen: set[int] = set()
    candidates: list[dict] = []

    async with httpx.AsyncClient() as client:
        for year in years:
            year_movies = await _fetch_year(client, year, limiter, sem)
            new_count = 0
            for m in year_movies:
                mid = m.get("id")
                if mid is None or mid in seen:
                    continue
                seen.add(mid)
                candidates.append({
                    "id": mid,
                    "title": m.get("original_title") or m.get("title") or "",
                    "popularity": m.get("popularity", 0.0),
                    "vote_count": m.get("vote_count", 0),
                })
                new_count += 1
            logger.info("  year=%d: %d returned, %d new (running total: %d)",
                        year, len(year_movies), new_count, len(candidates))

    # Sort by popularity desc — matches the artifact ordering downstream uses for
    # the dev seed slice (top-N by popularity).
    candidates.sort(key=lambda x: x["popularity"], reverse=True)
    logger.info("Total candidates: %d", len(candidates))
    return candidates


def run(end_year: int | None = None, output_path: str | None = None, upload: bool = True) -> None:
    """
    Build the candidate list. Uploads to GCS at BLOB_NAME by default; pass
    `upload=False` and `output_path` to dump locally for inspection.
    """
    logger.info("=== TMDb Candidate List Builder ===")
    if end_year is None:
        end_year = datetime.datetime.utcnow().year

    candidates = asyncio.run(_build_async(end_year))

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(output_path) if output_path else Path(tmpdir) / "movie_ids_to_crawl.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(candidates, f)
        logger.info("Wrote %s (%d entries)", out, len(candidates))

        if upload:
            gcs.upload_from_file(out, BLOB_NAME)
            logger.info("Uploaded to gs://%s/%s", settings.gcs_bucket, BLOB_NAME)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Build TMDb candidate list via /discover.")
    parser.add_argument("--end-year", type=int, default=None,
                        help="Latest year to query (default: current year)")
    parser.add_argument("--output", type=str, default=None,
                        help="Local output path (default: GCS upload only)")
    parser.add_argument("--no-upload", action="store_true",
                        help="Skip GCS upload — useful for local testing")
    args = parser.parse_args()
    run(end_year=args.end_year, output_path=args.output, upload=not args.no_upload)


if __name__ == "__main__":
    main()
