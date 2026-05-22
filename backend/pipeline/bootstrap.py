#!/usr/bin/env python3
"""
Connactor Bootstrap — one-command local Neo4j setup.

Dev mode (default): crawls top N movies (default 1000), enriches persons, loads into Neo4j (~15 min per 1000).
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

# Ensure ingest package (pipeline/) and utils/settings (backend/) are importable.
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR.parent))

import utils.gcs as gcs
from ingest.crawl_credits import run as crawl_credits
from ingest.crawl_delta import run as crawl_delta
from ingest.crawl_persons import run as crawl_persons
from ingest.download_movie_ids import run as download_ids
from ingest.load_neo4j import run as load_neo4j

logger = logging.getLogger(__name__)

DEV_BLOB = "pipeline/movie_ids_dev.json"
PROD_BLOB = "pipeline/movie_ids_to_crawl.json"
DEV_SAMPLE_SIZE_DEFAULT = 1000


def _build_dev_blob(sample_size: int, force: bool = False) -> None:
    if not force and gcs.blob_exists(DEV_BLOB):
        logger.info("[%s] already exists in GCS — skipping dev slice (use --force-dev to rebuild).", DEV_BLOB)
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        full_path = Path(tmpdir) / "full.json"
        if not gcs.download_to_file(PROD_BLOB, full_path):
            raise RuntimeError(f"Full movie list not found in GCS: {PROD_BLOB}")

        with open(full_path) as f:
            movies = json.load(f)

        dev_movies = movies[:sample_size]
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
    parser.add_argument("--dev-size", type=int, default=DEV_SAMPLE_SIZE_DEFAULT,
                        help="Number of top movies for dev mode (default: %(default)s)")
    parser.add_argument("--force-dev", action="store_true",
                        help="Rebuild the dev movie slice in GCS even if it already exists")
    parser.add_argument("--delta", action="store_true",
                        help="Delta refresh: only re-crawl movies changed in TMDB since yesterday "
                             "(via /movie/changes). Skips download_ids and dev-slice steps. "
                             "Requires --mode prod.")
    args = parser.parse_args()

    if args.delta and args.mode != "prod":
        parser.error("--delta requires --mode prod")

    logger.info("=== Connactor Bootstrap (mode=%s%s) ===", args.mode, ", delta" if args.delta else "")

    if args.delta:
        movies_blob = PROD_BLOB
        if not args.skip_credits:
            _step("Crawl delta credits", crawl_delta)
    else:
        if not args.skip_download:
            _step("Download movie IDs", download_ids)

        if args.mode == "dev":
            _step(
                f"Build dev seed (top {args.dev_size})",
                lambda: _build_dev_blob(args.dev_size, force=args.force_dev),
            )
            movies_blob = DEV_BLOB
        else:
            movies_blob = PROD_BLOB

        if not args.skip_credits:
            _step("Crawl credits", lambda: crawl_credits(movies_blob=movies_blob))

    if not args.skip_persons:
        _step("Enrich persons", crawl_persons)

    _step("Load Neo4j", lambda: load_neo4j(movies_blob=movies_blob))

    logger.info("=== Bootstrap complete (%s mode%s) ===", args.mode, ", delta" if args.delta else "")


if __name__ == "__main__":
    main()
