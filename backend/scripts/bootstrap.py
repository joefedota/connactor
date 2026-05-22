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
import logging
import sys
import tempfile
import time
from pathlib import Path

# Ensure ingest/utils packages (scripts/) and settings (backend/) are importable.
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR.parent))

import utils.gcs as gcs
from ingest.crawl_credits import run as crawl_credits
from ingest.crawl_persons import run as crawl_persons
from ingest.download_movie_ids import run as download_ids
from ingest.load_neo4j import run as load_neo4j

logger = logging.getLogger(__name__)

DEV_BLOB = "pipeline/movie_ids_dev.json"
PROD_BLOB = "pipeline/movie_ids_to_crawl.json"
DEV_SAMPLE_SIZE = 1000


def _build_dev_blob() -> None:
    if gcs.blob_exists(DEV_BLOB):
        logger.info("[%s] already exists in GCS — skipping dev slice.", DEV_BLOB)
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

        logger.info("Uploading dev seed (%d movies) to GCS: %s", len(dev_movies), DEV_BLOB)
        gcs.upload_from_file(dev_path, DEV_BLOB)


def _step(name: str, fn) -> None:
    logger.info("=" * 60)
    logger.info("STEP: %s", name)
    logger.info("=" * 60)
    t0 = time.monotonic()
    fn()
    logger.info("[%s] done in %.1fs", name, time.monotonic() - t0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Bootstrap local Neo4j from TMDB data via GCS.")
    parser.add_argument("--mode", choices=["dev", "prod"], default="dev")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-credits", action="store_true")
    parser.add_argument("--skip-persons", action="store_true")
    args = parser.parse_args()

    logger.info("=== Connactor Bootstrap (mode=%s) ===", args.mode)

    if not args.skip_download:
        _step("Download movie IDs", download_ids)

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

    logger.info("=== Bootstrap complete (%s mode) ===", args.mode)


if __name__ == "__main__":
    main()
