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
                m.original_language = row.original_language
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
    fame_score = vote_count of the actor's 3rd-most-voted movie. Heavily skews toward
    English-language Hollywood because TMDB vote_count comes from TMDB's mostly
    English-speaking user base — the K-drama-popular-but-Western-unknown bias of
    `a.rank` (TMDB global popularity) goes away.

    Robust to one-hit wonders — needs at least three reasonably-voted films to score
    high. Actors with <3 movies fall back to their lowest available vote_count
    (or 0 if they have none).

    fame_rank = 0-indexed rank by fame_score DESC. Same shape as a.rank so the
    /game tier bucketing keeps working.
    """
    logger.info("Computing fame_score for each actor ...")
    # Subquery (CALL { WITH a; MATCH ... ORDER BY ... }) lets each actor's
    # vote_counts be sorted independently before collecting.
    await session.run(
        """
        MATCH (a:Actor)
        CALL {
            WITH a
            MATCH (a)-[:APPEARED_IN]->(m:Movie)
            WHERE m.vote_count IS NOT NULL
            WITH m.vote_count AS vc
            ORDER BY vc DESC
            RETURN collect(vc) AS sorted_desc
        }
        WITH a,
             CASE
               WHEN size(sorted_desc) >= 3 THEN sorted_desc[2]
               WHEN size(sorted_desc) > 0  THEN sorted_desc[size(sorted_desc) - 1]
               ELSE 0
             END AS fame_score
        SET a.fame_score = fame_score
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
