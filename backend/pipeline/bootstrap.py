#!/usr/bin/env python3
"""
Connactor pipeline orchestrator.

Re-crawls TMDB for credits + movie details, enriches persons, and idempotently
MERGEs everything into Neo4j on every run. Designed to run daily as a Cloud Run
Job — there is no separate "delta" path; TMDB calls are cheap and our graph is
small, so a full re-crawl is simpler and keeps vote_counts (and therefore
fame_rank) always-fresh.

Dev mode: top N movies (default 1000), ~15 min per 1000.
Prod mode: full dataset (~35k movies, ~35 min end-to-end).

All intermediate artifacts live in GCS. Neo4j must be running.
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
from ingest.build_candidate_list import run as build_candidates
from ingest.crawl_credits import run as crawl_credits
from ingest.crawl_movie_details import run as crawl_movie_details
from ingest.crawl_persons import run as crawl_persons
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
    parser.add_argument("--skip-movie-details", action="store_true")
    parser.add_argument("--skip-persons", action="store_true")
    parser.add_argument("--dev-size", type=int, default=DEV_SAMPLE_SIZE_DEFAULT,
                        help="Number of top movies for dev mode (default: %(default)s)")
    parser.add_argument("--force-dev", action="store_true",
                        help="Rebuild the dev movie slice in GCS even if it already exists")
    args = parser.parse_args()

    logger.info("=== Connactor pipeline (mode=%s) ===", args.mode)

    if not args.skip_download:
        # Discover-based candidate list (#91): vote_count >= 100, year-sharded.
        # Cheap (~1-2 min) so we always run fresh — picks up new movies that
        # crossed the vote_count threshold since the last run.
        _step("Build candidate list (TMDb /discover)", build_candidates)

    if args.mode == "dev":
        _step(
            f"Build dev seed (top {args.dev_size})",
            lambda: _build_dev_blob(args.dev_size, force=args.force_dev),
        )
        movies_blob = DEV_BLOB
    else:
        movies_blob = PROD_BLOB

    # All three crawls run with force=True on daily runs so we always re-fetch from
    # TMDB rather than resume from checkpoint. Cheap (~35 min total) and gives us
    # always-fresh vote_counts, cast updates, and person metadata — meaning
    # fame_rank reflects current TMDB state every morning.
    if not args.skip_credits:
        _step("Crawl credits", lambda: crawl_credits(movies_blob=movies_blob, force=True))

    if not args.skip_movie_details:
        _step("Crawl movie details", lambda: crawl_movie_details(movies_blob=movies_blob, force=True))

    if not args.skip_persons:
        _step("Enrich persons", crawl_persons)

    _step("Load Neo4j", lambda: load_neo4j(movies_blob=movies_blob))

    logger.info("=== Pipeline complete (%s mode) ===", args.mode)


if __name__ == "__main__":
    main()
