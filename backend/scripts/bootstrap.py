#!/usr/bin/env python3
"""
Connactor Bootstrap — one-command local Neo4j setup.

Dev mode (default): crawls top 1000 movies, enriches persons, loads into Neo4j (~15 min).
Prod mode: full dataset (~35k movies, ~4-6 hrs).

All intermediate artifacts live in GCS. Neo4j must be running before calling this script.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

# Ensure ingest package is importable when running as `uv run python scripts/bootstrap.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest import gcs
from ingest.crawl_credits import run as crawl_credits
from ingest.crawl_persons import run as crawl_persons
from ingest.download_movie_ids import run as download_ids
from ingest.load_neo4j import run as load_neo4j

DEV_BLOB = "pipeline/movie_ids_dev.json"
PROD_BLOB = "pipeline/movie_ids_to_crawl.json"
DEV_SAMPLE_SIZE = 1000


def _build_dev_blob() -> None:
    """Slice top 1000 movies from full list and upload as dev seed."""
    if gcs.blob_exists(DEV_BLOB):
        print(f"  [{DEV_BLOB}] already exists in GCS — skipping dev slice.")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        full_path = Path(tmpdir) / "full.json"
        if not gcs.download_to_file(PROD_BLOB, full_path):
            raise RuntimeError(f"Full movie list not found in GCS: {PROD_BLOB}")

        with open(full_path) as f:
            movies = json.load(f)

        dev_movies = movies[:DEV_SAMPLE_SIZE]
        dev_path = Path(tmpdir) / "dev.json"
        with open(dev_path, "w") as f:
            json.dump(dev_movies, f)

        print(f"  Uploading dev seed ({len(dev_movies)} movies) to GCS: {DEV_BLOB}")
        gcs.upload_from_file(dev_path, DEV_BLOB)


def _step(name: str, fn) -> None:
    print(f"\n{'='*60}")
    print(f"  STEP: {name}")
    print(f"{'='*60}")
    t0 = time.monotonic()
    fn()
    elapsed = time.monotonic() - t0
    print(f"  [{name}] done in {elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap local Neo4j from TMDB data via GCS.")
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        default="dev",
        help="dev: top 1000 movies (~15 min). prod: full ~35k movies (~4-6 hrs).",
    )
    parser.add_argument("--skip-download", action="store_true", help="Skip TMDB export download step.")
    parser.add_argument("--skip-credits", action="store_true", help="Skip movie credits crawl step.")
    parser.add_argument("--skip-persons", action="store_true", help="Skip person enrichment step.")
    args = parser.parse_args()

    print(f"=== Connactor Bootstrap (mode={args.mode}) ===")

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    if not args.skip_download:
        _step("Download movie IDs", download_ids)

    movies_blob: str
    if args.mode == "dev":
        _step("Build dev seed (top 1000)", _build_dev_blob)
        movies_blob = DEV_BLOB
    else:
        movies_blob = PROD_BLOB

    if not args.skip_credits:
        _step("Crawl credits", lambda: crawl_credits(movies_blob=movies_blob))

    if not args.skip_persons:
        _step("Enrich persons", crawl_persons)

    _step("Load Neo4j", lambda: load_neo4j(movies_blob=movies_blob))

    print(f"\n=== Bootstrap complete ({args.mode} mode) ===")
    print("  Run verification queries:")
    print("    docker exec connactor-neo4j-dev cypher-shell -u neo4j -p connactorpassword \\")
    print('      "MATCH (a:Actor) RETURN count(a) AS actors;"')


if __name__ == "__main__":
    main()
