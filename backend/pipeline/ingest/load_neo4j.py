#!/usr/bin/env python3
"""
Neo4j Bulk Data Loader (Phase 1 Ticket 6 / Issue #6)

Loads persons_crawl.jsonl, credits_crawl.jsonl, and movies JSON from GCS into Neo4j.
- Applies schema (constraints + indexes) from migrations/schema.cql.
- Loads Actor nodes, Movie nodes, then APPEARED_IN edges in batches.
- Uses MERGE to be idempotent — safe to re-run on existing data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import tempfile
from pathlib import Path

import jsonlines
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ClientError
from tqdm import tqdm

import utils.gcs as gcs
from settings import settings

logger = logging.getLogger(__name__)

PERSONS_BLOB = "pipeline/persons_crawl.jsonl"
CREDITS_BLOB = "pipeline/credits_crawl.jsonl"
DETAILS_BLOB = "pipeline/movie_details.jsonl"

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "migrations" / "schema.cql"

ACTOR_BATCH = 1000
MOVIE_BATCH = 1000
EDGE_BATCH = 5000

_SCHEMA_ALREADY_EXISTS_CODES = {
    "Neo.ClientError.Schema.EquivalentSchemaRuleAlreadyExists",
    "Neo.ClientError.Schema.ConstraintAlreadyExists",
    "Neo.ClientError.Schema.IndexAlreadyExists",
}


def _get_neo4j_driver():
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def _load_jsonl(path: Path) -> list[dict]:
    with jsonlines.open(path) as reader:
        return list(reader)


async def _apply_schema(session) -> None:
    logger.info("Applying schema ...")
    statements = [s.strip() for s in SCHEMA_PATH.read_text().split(";") if s.strip()]
    for stmt in statements:
        try:
            await session.run(stmt)
        except ClientError as e:
            if e.code not in _SCHEMA_ALREADY_EXISTS_CODES:
                raise


async def _load_actors(session, persons: list[dict]) -> None:
    logger.info("Loading %d Actor nodes ...", len(persons))
    persons_sorted = sorted(persons, key=lambda p: p.get("popularity", 0.0), reverse=True)
    rows = [{**p, "rank": i} for i, p in enumerate(persons_sorted)]
    for i in tqdm(range(0, len(rows), ACTOR_BATCH), desc="Actor nodes", unit="batch"):
        await session.run(
            """
            UNWIND $rows AS row
            MERGE (a:Actor {person_id: row.person_id})
            SET a.name = row.name, a.popularity = row.popularity,
                a.rank = row.rank, a.profile_path = row.profile_path,
                a.birth_year = row.birth_year
            """,
            rows=rows[i : i + ACTOR_BATCH],
        )


async def _load_movies(session, movies: list[dict], details: dict[int, dict]) -> None:
    logger.info("Loading %d Movie nodes ...", len(movies))
    # `movies` comes from the daily ID export (id + popularity only); `details` is the
    # per-movie /movie/{id} crawl that fills in vote_count, year, etc. We join on id.
    rows = []
    for m in movies:
        d = details.get(m["id"], {})
        rows.append({
            "movie_id": m["id"],
            "title": m["title"],
            "popularity": m.get("popularity"),
            "year": d.get("year"),
            "vote_count": d.get("vote_count"),
            "vote_average": d.get("vote_average"),
            "runtime": d.get("runtime"),
            "original_language": d.get("original_language"),
            "collection_id": d.get("collection_id"),
        })
    for i in tqdm(range(0, len(rows), MOVIE_BATCH), desc="Movie nodes", unit="batch"):
        await session.run(
            """
            UNWIND $rows AS row
            MERGE (m:Movie {movie_id: row.movie_id})
            SET m.title = row.title,
                m.popularity = row.popularity,
                m.year = row.year,
                m.vote_count = row.vote_count,
                m.vote_average = row.vote_average,
                m.runtime = row.runtime,
                m.original_language = row.original_language,
                m.collection_id = row.collection_id
            """,
            rows=rows[i : i + MOVIE_BATCH],
        )


async def _load_edges(session, credits: list[dict]) -> None:
    logger.info("Loading %d APPEARED_IN edges ...", len(credits))
    for i in tqdm(range(0, len(credits), EDGE_BATCH), desc="APPEARED_IN edges", unit="batch"):
        await session.run(
            """
            UNWIND $rows AS row
            MATCH (a:Actor {person_id: row.person_id})
            MATCH (m:Movie {movie_id: row.movie_id})
            MERGE (a)-[r:APPEARED_IN]->(m)
            SET r.character = row.character, r.order = row.order
            """,
            rows=credits[i : i + EDGE_BATCH],
        )


async def _compute_fame_rank(session) -> None:
    """
    Composite fame_score from three signals:

    - strength: median of the top-5 collapsed group scores. Movies are first
      weighted by billing order (1.0 for top-3 billed, 0.5 for 4-9, 0.2 for 10+)
      and then grouped by belongs_to_collection (franchise dedup — 3 LOTR films
      count once). For each group we keep max(weighted_vote_count). Movies with
      no collection_id are each their own group.
    - popularity: TMDB's daily-updated popularity score for the actor. Captures
      "is this person culturally present right now," which raw vote_count of
      decade-old films doesn't.
    - lead_count: count of top-5 groups where the actor was top-3 billed AND the
      group's highest-voted movie has vote_count > 1000. Bonus for actually
      leading films, not just appearing in them.

    fame_score = log(1+strength)*1.0 + log(1+popularity)*1.0 + log(1+lead_count)*1.0

    Log-scaling keeps any one signal from dominating (vote_counts range 0→200k+;
    popularity 0→100; lead_count 0→5). Popularity weight was tuned down from 1.5 to
    1.0 after a preview showed actors with TMDB popularity spikes (e.g. John Hannah
    at p=42) crashing into the top 10. 1.0 keeps the signal meaningful without
    letting spikes dominate.

    fame_rank = 0-indexed by (fame_score DESC, popularity DESC, person_id ASC).
    Same shape as before so /game tier bucketing keeps working.
    """
    logger.info("Computing composite fame_score for each actor ...")
    await session.run(
        """
        MATCH (a:Actor)
        CALL {
            WITH a
            MATCH (a)-[r:APPEARED_IN]->(m:Movie)
            WHERE m.vote_count IS NOT NULL
            // Per-movie weighted vote_count (billing weight).
            WITH r, m,
                 m.vote_count *
                 CASE
                     WHEN r.order < 3  THEN 1.0
                     WHEN r.order < 10 THEN 0.5
                     ELSE 0.2
                 END AS weighted,
                 coalesce(m.collection_id, m.movie_id) AS group_key
            // Collapse by collection — one row per franchise (or per standalone movie).
            WITH group_key,
                 max(weighted) AS group_score,
                 min(r.order) AS group_min_order,
                 max(m.vote_count) AS group_max_votes
            ORDER BY group_score DESC
            RETURN collect({score: group_score, order: group_min_order, votes: group_max_votes}) AS groups
        }
        WITH a, groups[0..5] AS top5
        WITH a, top5,
             CASE
                 WHEN size(top5) >= 5 THEN top5[2].score
                 WHEN size(top5) >= 3 THEN top5[size(top5) / 2].score
                 WHEN size(top5) > 0  THEN top5[size(top5) - 1].score
                 ELSE 0
             END AS strength,
             size([g IN top5 WHERE g.order < 3 AND g.votes > 1000]) AS lead_count
        SET a.strength_score = strength,
            a.lead_count = lead_count,
            a.fame_score = log(1 + strength) * 1.0
                         + log(1 + coalesce(a.popularity, 0)) * 1.0
                         + log(1 + lead_count) * 1.0
        """
    )

    logger.info("Assigning fame_rank ...")
    await session.run(
        """
        MATCH (a:Actor)
        WITH a ORDER BY a.fame_score DESC, a.popularity DESC, a.person_id ASC
        WITH collect(a) AS actors
        UNWIND range(0, size(actors) - 1) AS i
        WITH actors[i] AS a, i AS rank
        SET a.fame_rank = rank
        """
    )


async def _log_counts(session) -> None:
    for label, query in [
        ("Actor nodes", "MATCH (a:Actor) RETURN count(a) AS n"),
        ("Movie nodes", "MATCH (m:Movie) RETURN count(m) AS n"),
        ("APPEARED_IN edges", "MATCH ()-[r:APPEARED_IN]->() RETURN count(r) AS n"),
    ]:
        result = await session.run(query)
        record = await result.single()
        logger.info("%s: %d", label, record["n"])


async def _load_async(movies_blob: str) -> None:
    driver = _get_neo4j_driver()
    try:
        await driver.verify_connectivity()
        logger.info("Neo4j connection OK.")
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to Neo4j at {settings.neo4j_uri}. Is it running? Error: {e}"
        ) from e

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        persons_path = tmpdir_path / "persons_crawl.jsonl"
        credits_path = tmpdir_path / "credits_crawl.jsonl"
        details_path = tmpdir_path / "movie_details.jsonl"
        movies_path = tmpdir_path / "movies.json"

        for blob, path in [(PERSONS_BLOB, persons_path), (CREDITS_BLOB, credits_path), (movies_blob, movies_path)]:
            logger.info("Downloading from GCS: %s", blob)
            if not gcs.download_to_file(blob, path):
                raise RuntimeError(f"GCS blob not found: {blob}")

        # Movie details are optional — older pipeline runs predate the crawler. Empty
        # mapping just means vote_count/year stay null for now (fame_rank ranks them
        # together at the bottom).
        details_by_id: dict[int, dict] = {}
        if gcs.blob_exists(DETAILS_BLOB):
            logger.info("Downloading from GCS: %s", DETAILS_BLOB)
            gcs.download_to_file(DETAILS_BLOB, details_path)
            details_by_id = {row["movie_id"]: row for row in _load_jsonl(details_path)}
            logger.info("Movie details available for %d movies", len(details_by_id))
        else:
            logger.warning("%s not in GCS — Movie nodes will have null vote_count/year", DETAILS_BLOB)

        persons = _load_jsonl(persons_path)
        credits = _load_jsonl(credits_path)
        with open(movies_path) as f:
            movies = json.load(f)

        async with driver.session() as session:
            await _apply_schema(session)
            await _load_actors(session, persons)
            await _load_movies(session, movies, details_by_id)
            await _load_edges(session, credits)
            await _compute_fame_rank(session)
            logger.info("Final counts:")
            await _log_counts(session)

    await driver.close()


def run(movies_blob: str) -> None:
    logger.info("=== Neo4j Bulk Loader ===")
    asyncio.run(_load_async(movies_blob))
    logger.info("Load complete.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Load crawled data into Neo4j.")
    parser.add_argument("--movies-blob", default="pipeline/movie_ids_to_crawl.json")
    args = parser.parse_args()
    run(movies_blob=args.movies_blob)


if __name__ == "__main__":
    main()
