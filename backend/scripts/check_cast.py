#!/usr/bin/env python3
"""
Debug tool: check whether an actor-movie connection exists in the Neo4j DB,
then cross-reference against the TMDB API to explain why it might be missing.

Three reasons a real connection can be absent from our DB:
  1. Movie not in our crawled set (filtered by vote_count/popularity at ingest time)
  2. Actor's known_for_department != "Acting" on TMDB
  3. Actor has < 5 credits in our crawled movie set (MIN_CREDITS threshold)

Usage (from backend/):
    uv run python scripts/check_cast.py --actor "Jon Bernthal" --movie "Wolf of Wall Street"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from settings import settings

MIN_CREDITS = 5
TMDB_BASE = "https://api.themoviedb.org/3"
HEADERS = {"Authorization": f"Bearer {settings.tmdb_api_read_token}"}


# ---------------------------------------------------------------------------
# Neo4j helpers (sync driver — simpler for a one-shot script)
# ---------------------------------------------------------------------------

def _neo4j_driver():
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def neo4j_search_actors(driver, name: str) -> list[dict]:
    with driver.session() as s:
        result = s.run(
            "CALL db.index.fulltext.queryNodes('actorNames', $search) "
            "YIELD node, score "
            "RETURN node.person_id AS id, node.name AS name, "
            "       node.popularity AS popularity, node.rank AS rank "
            "ORDER BY node.popularity DESC LIMIT 5",
            search=name + "*",
        )
        return [dict(r) for r in result]


def neo4j_search_movies(driver, title: str) -> list[dict]:
    with driver.session() as s:
        result = s.run(
            "CALL db.index.fulltext.queryNodes('movieTitles', $search) "
            "YIELD node, score "
            "RETURN node.movie_id AS id, node.title AS title, node.year AS year "
            "ORDER BY node.vote_count DESC LIMIT 5",
            search=title + "*",
        )
        return [dict(r) for r in result]


def neo4j_edge_exists(driver, person_id: int, movie_id: int) -> bool:
    with driver.session() as s:
        result = s.run(
            "MATCH (a:Actor {person_id: $pid})-[:APPEARED_IN]->(m:Movie {movie_id: $mid}) "
            "RETURN count(*) > 0 AS ok",
            pid=person_id,
            mid=movie_id,
        )
        record = result.single()
        return bool(record and record["ok"])


def neo4j_actor_exists(driver, person_id: int) -> bool:
    with driver.session() as s:
        result = s.run(
            "MATCH (a:Actor {person_id: $pid}) RETURN a.name AS name",
            pid=person_id,
        )
        return result.single() is not None


def neo4j_movie_exists(driver, movie_id: int) -> bool:
    with driver.session() as s:
        result = s.run(
            "MATCH (m:Movie {movie_id: $mid}) RETURN m.title AS title",
            mid=movie_id,
        )
        return result.single() is not None


def neo4j_actor_credit_count(driver, person_id: int) -> int:
    with driver.session() as s:
        result = s.run(
            "MATCH (a:Actor {person_id: $pid})-[:APPEARED_IN]->() RETURN count(*) AS n",
            pid=person_id,
        )
        record = result.single()
        return record["n"] if record else 0


# ---------------------------------------------------------------------------
# TMDB helpers
# ---------------------------------------------------------------------------

def tmdb_search_movie(title: str) -> list[dict]:
    resp = httpx.get(
        f"{TMDB_BASE}/search/movie",
        headers=HEADERS,
        params={"query": title, "include_adult": "false"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])[:5]


def tmdb_search_person(name: str) -> list[dict]:
    resp = httpx.get(
        f"{TMDB_BASE}/search/person",
        headers=HEADERS,
        params={"query": name},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])[:5]


def tmdb_movie_credits(movie_id: int) -> list[dict]:
    resp = httpx.get(
        f"{TMDB_BASE}/movie/{movie_id}/credits",
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("cast", [])


# ---------------------------------------------------------------------------
# Interactive selection
# ---------------------------------------------------------------------------

def _select(items: list[dict], label_fn, kind: str, query: str) -> dict | None:
    if not items:
        return None
    if len(items) == 1:
        print(f"  Found: {label_fn(items[0])}")
        return items[0]
    print(f"\nMultiple matches for {kind} '{query}':")
    for i, item in enumerate(items):
        print(f"  [{i + 1}] {label_fn(item)}")
    while True:
        choice = input(f"Select (1-{len(items)}) or Enter to skip: ").strip()
        if not choice:
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                return items[idx]
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Main diagnostic
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Check actor-movie connection in Neo4j and TMDB")
    parser.add_argument("--actor", help="Actor name")
    parser.add_argument("--movie", help="Movie title")
    args = parser.parse_args()

    actor_query = args.actor or input("Actor name: ").strip()
    movie_query = args.movie or input("Movie title: ").strip()

    print("\n" + "=" * 60)
    print(f"  Checking: '{actor_query}' ↔ '{movie_query}'")
    print("=" * 60)

    driver = _neo4j_driver()

    # ── Step 1: Find actor in Neo4j ─────────────────────────────────────────
    print(f"\n[1] Searching Neo4j for actor '{actor_query}' ...")
    actor_hits = neo4j_search_actors(driver, actor_query)
    actor = _select(
        actor_hits,
        lambda a: f"{a['name']}  (person_id={a['id']}, popularity={a['popularity']:.1f}, rank={a['rank']})",
        "actor",
        actor_query,
    )
    actor_in_neo4j = actor is not None
    if actor_in_neo4j:
        print(f"  ✓ Found in Neo4j: {actor['name']} (person_id={actor['id']})")
    else:
        print(f"  ✗ Not found in Neo4j (will check TMDB)")

    # ── Step 2: Find movie in Neo4j ─────────────────────────────────────────
    print(f"\n[2] Searching Neo4j for movie '{movie_query}' ...")
    movie_hits = neo4j_search_movies(driver, movie_query)
    movie = _select(
        movie_hits,
        lambda m: f"{m['title']} ({m['year']})  movie_id={m['id']}",
        "movie",
        movie_query,
    )
    movie_in_neo4j = movie is not None
    if movie_in_neo4j:
        print(f"  ✓ Found in Neo4j: {movie['title']} ({movie['year']})  movie_id={movie['id']}")
    else:
        print(f"  ✗ Not found in Neo4j (will check TMDB)")

    # ── Step 3: Check edge ───────────────────────────────────────────────────
    if actor_in_neo4j and movie_in_neo4j:
        print(f"\n[3] Checking APPEARED_IN edge in Neo4j ...")
        if neo4j_edge_exists(driver, actor["id"], movie["id"]):
            print(f"  ✓ Edge EXISTS — {actor['name']} → {movie['title']} is in the graph.")
            driver.close()
            return
        else:
            print(f"  ✗ No edge — both nodes exist but are NOT connected.")
    else:
        print(f"\n[3] Skipping edge check (one or both nodes missing from Neo4j)")

    # ── Step 4: Cross-reference TMDB ────────────────────────────────────────
    print(f"\n[4] Cross-referencing TMDB API ...")

    # Resolve TMDB movie_id
    tmdb_movie_id = movie["id"] if movie_in_neo4j else None
    if tmdb_movie_id is None:
        print(f"  Searching TMDB for movie '{movie_query}' ...")
        tmdb_movies = tmdb_search_movie(movie_query)
        tmdb_movie_match = _select(
            tmdb_movies,
            lambda m: f"{m['title']} ({m.get('release_date', '')[:4]})  id={m['id']}",
            "movie",
            movie_query,
        )
        if tmdb_movie_match:
            tmdb_movie_id = tmdb_movie_match["id"]
            print(f"  Found on TMDB: {tmdb_movie_match['title']}  id={tmdb_movie_id}")
        else:
            print(f"  ✗ Movie not found on TMDB either. Check the title spelling.")
            driver.close()
            return

    # Resolve TMDB person_id
    tmdb_person_id = actor["id"] if actor_in_neo4j else None
    if tmdb_person_id is None:
        print(f"  Searching TMDB for actor '{actor_query}' ...")
        tmdb_people = tmdb_search_person(actor_query)
        tmdb_person_match = _select(
            tmdb_people,
            lambda p: f"{p['name']}  id={p['id']}  known_for_department={p.get('known_for_department')}",
            "person",
            actor_query,
        )
        if tmdb_person_match:
            tmdb_person_id = tmdb_person_match["id"]
            print(f"  Found on TMDB: {tmdb_person_match['name']}  id={tmdb_person_id}")
        else:
            print(f"  ✗ Actor not found on TMDB either.")
            driver.close()
            return

    # Fetch movie credits from TMDB
    print(f"  Fetching TMDB credits for movie_id={tmdb_movie_id} ...")
    cast = tmdb_movie_credits(tmdb_movie_id)
    cast_by_id = {m["id"]: m for m in cast}
    cast_member = cast_by_id.get(tmdb_person_id)

    print(f"\n  TMDB cast size: {len(cast)}")

    if not cast_member:
        print(f"  ✗ {actor_query} is NOT in TMDB credits for this movie.")
        print(f"    → TMDB itself doesn't list this actor in this film's cast.")
        driver.close()
        return

    print(f"  ✓ {cast_member['name']} IS in TMDB credits:")
    print(f"    known_for_department : {cast_member.get('known_for_department')}")
    print(f"    character            : {cast_member.get('character')}")
    print(f"    order                : {cast_member.get('order')}")

    # ── Step 5: Explain why it's missing from our DB ─────────────────────────
    print(f"\n[5] Diagnosing why the connection is missing from Neo4j ...")

    dept = cast_member.get("known_for_department")
    if dept != "Acting":
        print(f"  ✗ ROOT CAUSE: known_for_department is '{dept}', not 'Acting'.")
        print(f"    Our pipeline filters to Acting-department cast only.")
        driver.close()
        return

    if not movie_in_neo4j:
        print(f"  ✗ ROOT CAUSE: Movie is not in Neo4j — it was likely filtered out")
        print(f"    at ingest time (vote_count or popularity threshold).")
        driver.close()
        return

    if not actor_in_neo4j:
        print(f"  ✗ ROOT CAUSE: Actor node is missing from Neo4j.")
        print(f"    The actor appeared in TMDB credits with known_for_department='Acting',")
        print(f"    but was excluded by the MIN_CREDITS={MIN_CREDITS} threshold in crawl_persons.py.")
        print(f"    This actor doesn't appear in enough movies in our crawled set.")
        driver.close()
        return

    # Both nodes exist, dept is Acting, but no edge → edge was dropped at load time
    credit_count = neo4j_actor_credit_count(driver, actor["id"])
    print(f"  Actor is in Neo4j with {credit_count} credits in our DB.")
    print(f"  ✗ ROOT CAUSE: The APPEARED_IN edge is missing despite both nodes existing.")
    print(f"    This means the edge was present in credits_crawl.jsonl but skipped")
    print(f"    by load_neo4j.py — most likely because the actor had < {MIN_CREDITS} credits")
    print(f"    at the time persons_crawl.jsonl was generated, so the Actor node")
    print(f"    wasn't created, and the MATCH in load_neo4j dropped the edge silently.")
    print(f"    Re-running the bootstrap (or adding a manual patch) will fix this.")

    driver.close()


if __name__ == "__main__":
    main()
