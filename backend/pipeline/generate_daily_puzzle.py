#!/usr/bin/env python3
"""Daily puzzle generator — run once per day via Cloud Scheduler.

Picks an easy actor pair (both fame_rank 0–50, i.e. top-50 most famous) and
upserts it into the puzzles table as tomorrow's daily puzzle. Pairs that have
already been used as a daily puzzle (on any previous date) are excluded so the
same matchup never repeats.

Usage:
    cd backend
    uv run python pipeline/generate_daily_puzzle.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import sys
from pathlib import Path

# Ensure backend/ root is importable (same pattern as pipeline/bootstrap.py).
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))           # pipeline/ — for ingest imports if needed
sys.path.insert(0, str(_HERE.parent))    # backend/ — for settings, app, etc.

from neo4j import AsyncGraphDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from settings import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 50
FAME_RANK_MIN = 0
FAME_RANK_MAX = 50


async def pick_pair(
    driver, excluded_pairs: set[tuple[int, int]]
) -> tuple[int, int, int] | None:
    """Return (source_id, target_id, optimal_hops) or None if no valid pair found.

    excluded_pairs: set of (source_id, target_id) used in previous daily puzzles.
    Both orderings are checked so (A, B) and (B, A) are treated as the same matchup.
    """
    for _ in range(MAX_ATTEMPTS):
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (a:Actor) WHERE a.fame_rank >= $min_rank AND a.fame_rank < $max_rank
                WITH a ORDER BY rand() LIMIT 2
                WITH collect(a) AS actors WHERE size(actors) = 2
                WITH actors[0] AS source, actors[1] AS target
                MATCH p = shortestPath((source)-[:APPEARED_IN*..12]-(target))
                RETURN source.person_id AS src, target.person_id AS tgt, length(p) AS hops
                """,
                min_rank=FAME_RANK_MIN,
                max_rank=FAME_RANK_MAX,
            )
            record = await result.single()
        if record:
            src, tgt, hops = int(record["src"]), int(record["tgt"]), int(record["hops"])
            if (src, tgt) not in excluded_pairs and (tgt, src) not in excluded_pairs:
                return src, tgt, hops
            logger.info("Skipping already-used pair (%d, %d) — retrying.", src, tgt)
    return None


async def main(target_date: datetime.date, force: bool = False) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    try:
        async with session_factory() as session:
            existing = await session.execute(
                text(
                    "SELECT puzzle_id FROM puzzles WHERE is_daily = TRUE AND scheduled_date = :d"
                ),
                {"d": target_date},
            )
            if existing.first():
                if not force:
                    logger.info("Daily puzzle for %s already exists — skipping.", target_date)
                    return
                logger.info("Daily puzzle for %s already exists — forcing regeneration.", target_date)

            # Load all previously used daily pairs so we never repeat a matchup.
            used_rows = await session.execute(
                text(
                    """
                    SELECT source_id, target_id FROM puzzles
                    WHERE is_daily = TRUE AND scheduled_date < :d
                    """
                ),
                {"d": target_date},
            )
            excluded_pairs: set[tuple[int, int]] = {
                (row.source_id, row.target_id) for row in used_rows
            }
        logger.info(
            "Picking pair for %s (excluding %d previously used pairs) ...",
            target_date,
            len(excluded_pairs),
        )
        result = await pick_pair(driver, excluded_pairs)
        if result is None:
            logger.error("Could not find a valid pair after %d attempts.", MAX_ATTEMPTS)
            sys.exit(1)

        src, tgt, hops = result
        logger.info("Selected: source=%d target=%d hops=%d", src, tgt, hops)

        async with session_factory() as session:
            # Unmark any existing daily entry for this date so only one row is
            # flagged is_daily=TRUE per scheduled_date after the insert.
            await session.execute(
                text(
                    """
                    UPDATE puzzles SET is_daily = FALSE, scheduled_date = NULL
                    WHERE is_daily = TRUE AND scheduled_date = :d
                    """
                ),
                {"d": target_date},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO puzzles (source_id, target_id, optimal_hops, is_daily, scheduled_date)
                    VALUES (:src, :tgt, :hops, TRUE, :d)
                    ON CONFLICT (source_id, target_id)
                    DO UPDATE SET is_daily = TRUE, scheduled_date = EXCLUDED.scheduled_date
                    """
                ),
                {"src": src, "tgt": tgt, "hops": hops, "d": target_date},
            )
            await session.commit()

        logger.info("Daily puzzle for %s saved.", target_date)
    finally:
        await driver.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default=None,
        help="Target date YYYY-MM-DD (default: tomorrow UTC)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if a puzzle already exists for the target date",
    )
    args = parser.parse_args()

    target = (
        datetime.date.fromisoformat(args.date)
        if args.date
        else datetime.date.today() + datetime.timedelta(days=1)
    )

    asyncio.run(main(target, force=args.force))
