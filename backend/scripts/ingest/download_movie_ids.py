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
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from ingest import gcs

BLOB_NAME = "pipeline/movie_ids_to_crawl.json"


def _download_file(url: str, dest_path: Path) -> bool:
    print(f"  Downloading from: {url}")
    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP Error: {e.code} - {e.reason}")
        return False
    except Exception as e:
        print(f"  Download error: {e}")
        return False


def _parse_and_filter_export(source_path: Path) -> list[dict]:
    filtered_movies = []
    total_count = 0
    print("  Parsing and filtering export ...")
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
    print(f"  Processed {total_count:,} total rows.")
    print(f"  Filtered to {len(filtered_movies):,} qualifying movies (popularity > 1.0).")
    return filtered_movies


def run(force: bool = False) -> None:
    print("=== TMDb Movie ID Downloader ===")

    if not force and gcs.blob_exists(BLOB_NAME):
        print(f"  [{BLOB_NAME}] already exists in GCS — skipping (use --force to re-download).")
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
            print(f"  Trying export for date: {date_str} ...")
            if _download_file(url, gz_path):
                success = True
                break
            print(f"  Export for {date_str} unavailable, trying fallback...")

        if not success:
            raise RuntimeError("Could not download any TMDb daily movie export files.")

        movies = _parse_and_filter_export(gz_path)

        out_path = Path(tmpdir) / "movie_ids_to_crawl.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(movies, f)

        print(f"  Uploading to GCS: {BLOB_NAME}")
        gcs.upload_from_file(out_path, BLOB_NAME)
        print(f"  Done — {len(movies):,} movies uploaded.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and filter TMDb movie ID export to GCS.")
    parser.add_argument("--force", action="store_true", help="Re-download even if GCS blob already exists.")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()
