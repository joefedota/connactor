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
import os
import tempfile
from pathlib import Path

from neo4j import AsyncGraphDatabase

from ingest import gcs

PERSONS_BLOB = "pipeline/persons_crawl.jsonl"
CREDITS_BLOB = "pipeline/credits_crawl.jsonl"

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "migrations" / "schema.cql"

ACTOR_BATCH = 1000
MOVIE_BATCH = 1000
EDGE_BATCH = 5000


def _get_neo4j_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "connactorpassword")
    return AsyncGraphDatabase.driver(uri, auth=(user, password))


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def _apply_schema(session) -> None:
    print("  Applying schema ...")
    statements = [s.strip() for s in SCHEMA_PATH.read_text().split(";") if s.strip()]
    for stmt in statements:
        try:
            await session.run(stmt)
        except Exception as e:
            if "EquivalentSchemaRuleAlreadyExists" not in str(e) and "already exists" not in str(e).lower():
                raise


async def _load_actors(session, persons: list[dict]) -> None:
    print(f"  Loading {len(persons):,} Actor nodes ...")
    persons_sorted = sorted(persons, key=lambda p: p.get("popularity", 0.0), reverse=True)
    rows = [
        {**p, "rank": i}
        for i, p in enumerate(persons_sorted)
    ]
    for i in range(0, len(rows), ACTOR_BATCH):
        batch = rows[i : i + ACTOR_BATCH]
        await session.run(
            """
            UNWIND $rows AS row
            MERGE (a:Actor {person_id: row.person_id})
            SET a.name = row.name,
                a.popularity = row.popularity,
                a.rank = row.rank,
                a.profile_path = row.profile_path,
                a.birth_year = row.birth_year
            """,
            rows=batch,
        )
    print(f"    Actors loaded.")


async def _load_movies(session, movies: list[dict]) -> None:
    print(f"  Loading {len(movies):,} Movie nodes ...")
    rows = [
        {
            "movie_id": m["id"],
            "title": m["title"],
            "popularity": m.get("popularity"),
            "year": m.get("year"),
            "vote_count": m.get("vote_count"),
        }
        for m in movies
    ]
    for i in range(0, len(rows), MOVIE_BATCH):
        batch = rows[i : i + MOVIE_BATCH]
        await session.run(
            """
            UNWIND $rows AS row
            MERGE (m:Movie {movie_id: row.movie_id})
            SET m.title = row.title,
                m.popularity = row.popularity,
                m.year = row.year,
                m.vote_count = row.vote_count
            """,
            rows=batch,
        )
    print(f"    Movies loaded.")


async def _load_edges(session, credits: list[dict]) -> None:
    print(f"  Loading {len(credits):,} APPEARED_IN edges ...")
    for i in range(0, len(credits), EDGE_BATCH):
        batch = credits[i : i + EDGE_BATCH]
        await session.run(
            """
            UNWIND $rows AS row
            MATCH (a:Actor {person_id: row.person_id})
            MATCH (m:Movie {movie_id: row.movie_id})
            MERGE (a)-[r:APPEARED_IN]->(m)
            SET r.character = row.character, r.order = row.order
            """,
            rows=batch,
        )
        print(f"    Edges: {min(i + EDGE_BATCH, len(credits)):,}/{len(credits):,}", end="\r")
    print()
    print(f"    Edges loaded.")


async def _log_counts(session) -> None:
    for label, query in [
        ("Actor nodes", "MATCH (a:Actor) RETURN count(a) AS n"),
        ("Movie nodes", "MATCH (m:Movie) RETURN count(m) AS n"),
        ("APPEARED_IN edges", "MATCH ()-[r:APPEARED_IN]->() RETURN count(r) AS n"),
    ]:
        result = await session.run(query)
        record = await result.single()
        print(f"  {label}: {record['n']:,}")


async def _load_async(movies_blob: str) -> None:
    driver = _get_neo4j_driver()
    try:
        await driver.verify_connectivity()
        print("  Neo4j connection OK.")
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to Neo4j. Is it running? Error: {e}\n"
            f"  URI: {os.environ.get('NEO4J_URI', 'bolt://localhost:7687')}"
        ) from e

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        persons_path = tmpdir_path / "persons_crawl.jsonl"
        credits_path = tmpdir_path / "credits_crawl.jsonl"
        movies_path = tmpdir_path / "movies.json"

        print(f"  Downloading persons from GCS: {PERSONS_BLOB}")
        if not gcs.download_to_file(PERSONS_BLOB, persons_path):
            raise RuntimeError(f"GCS blob not found: {PERSONS_BLOB}. Run crawl_persons first.")

        print(f"  Downloading credits from GCS: {CREDITS_BLOB}")
        if not gcs.download_to_file(CREDITS_BLOB, credits_path):
            raise RuntimeError(f"GCS blob not found: {CREDITS_BLOB}. Run crawl_credits first.")

        print(f"  Downloading movies from GCS: {movies_blob}")
        if not gcs.download_to_file(movies_blob, movies_path):
            raise RuntimeError(f"GCS blob not found: {movies_blob}. Run download_movie_ids first.")

        persons = _load_jsonl(persons_path)
        credits = _load_jsonl(credits_path)
        with open(movies_path) as f:
            movies = json.load(f)

        async with driver.session() as session:
            await _apply_schema(session)
            await _load_actors(session, persons)
            await _load_movies(session, movies)
            await _load_edges(session, credits)
            print("\n  Final counts:")
            await _log_counts(session)

    await driver.close()


def run(movies_blob: str) -> None:
    print("=== Neo4j Bulk Loader ===")
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
    asyncio.run(_load_async(movies_blob))
    print("  Load complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load crawled data into Neo4j.")
    parser.add_argument(
        "--movies-blob",
        default="pipeline/movie_ids_to_crawl.json",
        help="GCS blob name for the movies list.",
    )
    args = parser.parse_args()
    run(movies_blob=args.movies_blob)


if __name__ == "__main__":
    main()
