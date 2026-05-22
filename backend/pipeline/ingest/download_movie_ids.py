#!/usr/bin/env python3
"""
TMDb Movie ID Export Downloader (Phase 1 Ticket 2)

Downloads and parses the daily TMDb movie ID export.
- Fetches `https://files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz` (today, with yesterday fallback).
- Filters to `adult=false` and `popularity > 1.0`.
- Uploads filtered list to GCS at `pipeline/movie_ids_to_crawl.json`.
- Idempotent: skips download if blob already exists in GCS (unless force=True).
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import logging
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import utils.gcs as gcs

logger = logging.getLogger(__name__)

BLOB_NAME = "pipeline/movie_ids_to_crawl.json"


def _download_file(url: str, dest_path: Path) -> bool:
    logger.info("Downloading from: %s", url)
    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except urllib.error.HTTPError as e:
        logger.warning("HTTP Error: %d - %s", e.code, e.reason)
        return False
    except Exception:
        logger.exception("Download error")
        return False


def _parse_and_filter_export(source_path: Path) -> list[dict]:
    filtered_movies = []
    total_count = 0
    logger.info("Parsing and filtering export ...")
    with gzip.open(source_path, "rt", encoding="utf-8") as f:
        for line in f:
            total_count += 1
            try:
                movie = json.loads(line)
                if not movie.get("adult", True) and movie.get("popularity", 0.0) > 1.0:
                    filtered_movies.append({
                        "id": movie["id"],
                        "title": movie["original_title"],
                        "popularity": movie["popularity"],
                    })
            except (json.JSONDecodeError, KeyError):
                continue
    filtered_movies.sort(key=lambda x: x["popularity"], reverse=True)
    logger.info("Processed %d total rows. Filtered to %d qualifying movies.", total_count, len(filtered_movies))
    return filtered_movies


def run(force: bool = False) -> None:
    logger.info("=== TMDb Movie ID Downloader ===")

    if not force and gcs.blob_exists(BLOB_NAME):
        logger.info("[%s] already exists in GCS — skipping (use --force to re-download).", BLOB_NAME)
        return

    today = datetime.datetime.utcnow()
    dates_to_try = [
        today.strftime("%m_%d_%Y"),
        (today - datetime.timedelta(days=1)).strftime("%m_%d_%Y"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        gz_path = Path(tmpdir) / "movie_ids_temp.json.gz"
        success = False

        for date_str in dates_to_try:
            url = f"https://files.tmdb.org/p/exports/movie_ids_{date_str}.json.gz"
            logger.info("Trying export for date: %s ...", date_str)
            if _download_file(url, gz_path):
                success = True
                break

        if not success:
            raise RuntimeError("Could not download any TMDb daily movie export files.")

        movies = _parse_and_filter_export(gz_path)

        out_path = Path(tmpdir) / "movie_ids_to_crawl.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(movies, f)

        gcs.upload_from_file(out_path, BLOB_NAME)
        logger.info("Done — %d movies uploaded.", len(movies))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Download and filter TMDb movie ID export to GCS.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()
