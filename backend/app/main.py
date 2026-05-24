"""
FastAPI backend for Connactor.

Endpoints:
  GET  /game                                    — random actor pair
  POST /validate                                — validate user's current path
  POST /solve                                   — all optimal paths (give up / end)
  GET  /autocomplete?q=...&type=actor|movie     — prefix search (unconstrained)
  GET  /autocomplete/neighbors?node_id=...&type=actor|movie  — neighbors of a node
  GET  /connected?a=...&b=...                   — edge existence check
"""
from __future__ import annotations

import random
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from neo4j.exceptions import ClientError

from app.db import get_driver
from app.models import (
    AutocompleteResponse,
    Difficulty,
    GameResponse,
    NodeInfo,
    SolveRequest,
    SolveResponse,
    ValidateRequest,
    ValidateResponse,
)

MAX_GAME_ATTEMPTS = 20
MAX_PATH_HOPS = 12

# Lucene QueryParser special chars per Neo4j fulltext index (Lucene Classic syntax).
_LUCENE_SPECIALS = r'+-&|!(){}[]^"~*?:\/'
_LUCENE_ESCAPE_TABLE = str.maketrans({c: f"\\{c}" for c in _LUCENE_SPECIALS})


def _build_fulltext_query(q: str) -> str:
    """
    Turn a user query into a Lucene query with AND semantics.

    Each whitespace-delimited token is escaped and prefixed with `+` (required match).
    The last token also gets a trailing `*` so an in-progress word matches by prefix.
    Returns "" if no usable tokens remain — callers should short-circuit to an empty
    result rather than send "" to Neo4j (which would raise a parse error).
    """
    tokens = [t.translate(_LUCENE_ESCAPE_TABLE) for t in q.split() if t.strip()]
    if not tokens:
        return ""
    parts = [f"+{t}" for t in tokens[:-1]]
    parts.append(f"+{tokens[-1]}*")
    return " ".join(parts)

# Difficulty is determined by `a.fame_rank` — a 0-indexed rank where the actor's
# fame_score is the vote_count of their 3rd-most-voted movie. Heavily skews toward
# English-language Hollywood (TMDB vote_count comes from TMDB's mostly English-
# speaking user base). Each tier is a half-open interval; both actors are picked
# from the same tier so the experience is focused (easy = "two Hollywood A-listers",
# expert = "two niche actors") and we can find the pair in one indexed query with
# no retry-on-classification-mismatch loop.
_DIFFICULTY_RANK_RANGE: dict[Difficulty, tuple[int, int]] = {
    "easy":   (0,    50),
    "medium": (50,   200),
    "hard":   (200,  1000),
    "expert": (1000, 5000),
}
# Default (no difficulty filter) — anyone in the top 1000.
_DEFAULT_RANK_RANGE = (0, 1000)


def _classify_difficulty(rank_a: int, rank_b: int) -> Difficulty:
    max_rank = max(rank_a, rank_b)
    if max_rank < 50:
        return "easy"
    if max_rank < 200:
        return "medium"
    if max_rank < 1000:
        return "hard"
    return "expert"


@asynccontextmanager
async def lifespan(app: FastAPI):
    driver = get_driver()
    await driver.verify_connectivity()
    app.state.neo4j = driver
    yield
    await driver.close()


app = FastAPI(title="Connactor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _actor_to_node(record, key: str = "a") -> NodeInfo:
    node = record[key]
    return NodeInfo(
        type="actor",
        id=str(node["person_id"]),
        label=node["name"],
        popularity=node.get("popularity"),
    )


def _movie_to_node(record, key: str = "m") -> NodeInfo:
    node = record[key]
    return NodeInfo(
        type="movie",
        id=str(node["movie_id"]),
        label=node["title"],
        year=str(node["year"]) if node.get("year") else None,
    )


@app.get("/game", response_model=GameResponse)
async def get_game(
    request: Request,
    difficulty: Optional[Difficulty] = Query(None),
):
    min_rank, max_rank = _DIFFICULTY_RANK_RANGE[difficulty] if difficulty else _DEFAULT_RANK_RANGE
    driver = request.app.state.neo4j

    async with driver.session() as session:
        # Pick two random actors from the difficulty's rank tier in one indexed query,
        # then verify a path exists between them (capped at 12 hops). Most popular pairs
        # are 2-4 hops apart so this resolves in a single attempt; retry only if we
        # happen to pick a disconnected pair.
        for _ in range(MAX_GAME_ATTEMPTS):
            result = await session.run(
                f"""
                MATCH (a:Actor) WHERE a.fame_rank >= $min_rank AND a.fame_rank < $max_rank
                WITH a ORDER BY rand() LIMIT 2
                WITH collect(a) AS actors WHERE size(actors) = 2
                WITH actors[0] AS source, actors[1] AS target
                MATCH p = shortestPath((source)-[:APPEARED_IN*..{MAX_PATH_HOPS}]-(target))
                RETURN source, target
                """,
                min_rank=min_rank,
                max_rank=max_rank,
            )
            record = await result.single()
            if record is None:
                continue

            source = record["source"]
            target = record["target"]
            return GameResponse(
                game_id=str(uuid.uuid4()),
                source=NodeInfo(
                    type="actor",
                    id=str(source["person_id"]),
                    label=source["name"],
                    popularity=source.get("popularity"),
                ),
                target=NodeInfo(
                    type="actor",
                    id=str(target["person_id"]),
                    label=target["name"],
                    popularity=target.get("popularity"),
                ),
                difficulty=_classify_difficulty(source["fame_rank"], target["fame_rank"]),
            )

    raise HTTPException(status_code=503, detail="Could not find a valid pair. Try again.")


@app.post("/validate", response_model=ValidateResponse)
async def post_validate(request: Request, body: ValidateRequest):
    driver = request.app.state.neo4j
    path = body.path

    if not path:
        return ValidateResponse(valid=False, error="Path is empty")
    if path[0] != body.source_id:
        return ValidateResponse(valid=False, error=f"Path must start with source actor {body.source_id}")
    if len(path) < 3:
        return ValidateResponse(valid=False, error="Path must have at least 3 nodes (actor → movie → actor)")
    if len(path) % 2 == 0:
        return ValidateResponse(valid=False, error="Path length must be odd (actor → movie → actor → ...)")

    # Check for repeated movies
    movie_ids_seen: set[str] = set()
    for i, node_id in enumerate(path):
        if i % 2 == 1:  # movie position
            if node_id in movie_ids_seen:
                return ValidateResponse(valid=False, error=f"Movie {node_id} appears twice in the path")
            movie_ids_seen.add(node_id)

    # Build edge list: [(actor_id, movie_id), ...]
    edges = [
        (int(path[i]), int(path[i + 1]))
        for i in range(0, len(path) - 1, 2)
    ]

    async with driver.session() as session:
        # Check all edges exist in one query
        result = await session.run(
            """
            UNWIND $edges AS edge
            OPTIONAL MATCH (a:Actor {person_id: edge[0]})-[:APPEARED_IN]->(m:Movie {movie_id: edge[1]})
            RETURN edge[0] AS actor_id, edge[1] AS movie_id, m IS NOT NULL AS valid
            """,
            edges=edges,
        )
        records = await result.data()

    for row in records:
        if not row["valid"]:
            return ValidateResponse(
                valid=False,
                error=f"Actor {row['actor_id']} did not appear in movie {row['movie_id']}",
            )

    is_complete = path[-1] == body.target_id
    is_optimal: Optional[bool] = None

    if is_complete:
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH p = shortestPath(
                    (a1:Actor {person_id: $source})-[:APPEARED_IN*..12]-(a2:Actor {person_id: $target})
                )
                RETURN length(p) AS hops
                """,
                source=int(body.source_id),
                target=int(body.target_id),
            )
            record = await result.single()
        if record:
            min_hops = record["hops"]
            player_hops = len(path) - 1
            is_optimal = player_hops == min_hops

    return ValidateResponse(valid=True, is_complete=is_complete, is_optimal=is_optimal)


@app.post("/solve", response_model=SolveResponse)
async def post_solve(request: Request, body: SolveRequest):
    driver = request.app.state.neo4j

    if body.source_id == body.target_id:
        async with driver.session() as session:
            result = await session.run(
                "MATCH (a:Actor {person_id: $id}) RETURN a.name AS name, a.popularity AS popularity",
                id=int(body.source_id),
            )
            record = await result.single()
        if not record:
            raise HTTPException(status_code=404, detail="Actor not found.")
        node = NodeInfo(
            type="actor",
            id=body.source_id,
            label=record["name"],
            popularity=record.get("popularity"),
        )
        return SolveResponse(hop_count=0, paths=[[node]])

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH p = allShortestPaths(
                (a1:Actor {person_id: $source})-[:APPEARED_IN*..12]-(a2:Actor {person_id: $target})
            )
            RETURN [n IN nodes(p) | CASE labels(n)[0]
                WHEN 'Actor' THEN {type: 'actor', id: toString(n.person_id), label: n.name,  popularity: n.popularity}
                WHEN 'Movie' THEN {type: 'movie', id: toString(n.movie_id),  label: n.title, year: toString(n.year)}
            END] AS path,
            length(p) AS hops
            LIMIT 10
            """,
            source=int(body.source_id),
            target=int(body.target_id),
        )
        records = await result.data()

    if not records:
        raise HTTPException(status_code=404, detail="No path exists between these actors.")

    hop_count = records[0]["hops"]
    paths = [
        [NodeInfo(**node) for node in rec["path"]]
        for rec in records
    ]
    return SolveResponse(hop_count=hop_count, paths=paths)


@app.get("/autocomplete", response_model=AutocompleteResponse)
async def get_autocomplete(
    request: Request,
    q: str = Query(..., min_length=2),
    type: str = Query(..., pattern="^(actor|movie)$"),
    limit: int = Query(10, ge=1, le=20),
):
    search = _build_fulltext_query(q)
    if not search:
        return AutocompleteResponse(results=[])

    driver = request.app.state.neo4j

    async with driver.session() as session:
        try:
            if type == "actor":
                result = await session.run(
                    """
                    CALL db.index.fulltext.queryNodes('actorNames', $search)
                    YIELD node, score
                    RETURN node.person_id AS id, node.name AS label,
                           node.popularity AS popularity, node.profile_path AS profile_path
                    ORDER BY score DESC, node.popularity DESC
                    LIMIT $limit
                    """,
                    search=search,
                    limit=limit,
                )
            else:
                result = await session.run(
                    """
                    CALL db.index.fulltext.queryNodes('movieTitles', $search)
                    YIELD node, score
                    RETURN node.movie_id AS id, node.title AS label,
                           node.year AS year, node.vote_count AS vote_count
                    ORDER BY score DESC, node.vote_count DESC
                    LIMIT $limit
                    """,
                    search=search,
                    limit=limit,
                )
            records = await result.data()
        except ClientError:
            # Malformed Lucene query (e.g. user typed only escape-special chars) —
            # return empty rather than 500.
            return AutocompleteResponse(results=[])

    results = []
    for rec in records:
        if type == "actor":
            results.append(NodeInfo(
                type="actor",
                id=str(rec["id"]),
                label=rec["label"],
                popularity=rec.get("popularity"),
            ))
        else:
            results.append(NodeInfo(
                type="movie",
                id=str(rec["id"]),
                label=rec["label"],
                year=str(rec["year"]) if rec.get("year") else None,
            ))

    return AutocompleteResponse(results=results)


@app.get("/autocomplete/neighbors", response_model=AutocompleteResponse)
async def get_autocomplete_neighbors(
    request: Request,
    node_id: str = Query(...),
    type: str = Query(..., pattern="^(actor|movie)$"),
    q: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
):
    driver = request.app.state.neo4j

    async with driver.session() as session:
        if type == "actor":
            # node_id is a movie — fetch its actors
            cypher = """
                MATCH (m:Movie {movie_id: $node_id})<-[:APPEARED_IN]-(a:Actor)
                WHERE $q = '' OR toLower(a.name) CONTAINS toLower($q)
                RETURN a.person_id AS id, a.name AS label, a.popularity AS popularity
                ORDER BY a.popularity DESC
                LIMIT $limit
            """
        else:
            # node_id is an actor — fetch their movies
            cypher = """
                MATCH (a:Actor {person_id: $node_id})-[:APPEARED_IN]->(m:Movie)
                WHERE $q = '' OR toLower(m.title) CONTAINS toLower($q)
                RETURN m.movie_id AS id, m.title AS label, m.year AS year, m.vote_count AS vote_count
                ORDER BY m.vote_count DESC
                LIMIT $limit
            """
        result = await session.run(cypher, node_id=int(node_id), q=q, limit=limit)
        records = await result.data()

    results = []
    for rec in records:
        if type == "actor":
            results.append(NodeInfo(
                type="actor",
                id=str(rec["id"]),
                label=rec["label"],
                popularity=rec.get("popularity"),
            ))
        else:
            results.append(NodeInfo(
                type="movie",
                id=str(rec["id"]),
                label=rec["label"],
                year=str(rec["year"]) if rec.get("year") else None,
            ))

    return AutocompleteResponse(results=results)


@app.get("/connected")
async def get_connected(
    request: Request,
    a: str = Query(...),
    b: str = Query(...),
):
    # The frontend calls this with adjacent path nodes (always actor+movie in either order).
    # Try both orderings so either (actor_id, movie_id) or (movie_id, actor_id) works.
    driver = request.app.state.neo4j
    async with driver.session() as session:
        result = await session.run(
            """
            RETURN EXISTS {
                MATCH (:Actor {person_id: $a})-[:APPEARED_IN]->(:Movie {movie_id: $b})
            } OR EXISTS {
                MATCH (:Actor {person_id: $b})-[:APPEARED_IN]->(:Movie {movie_id: $a})
            } AS connected
            """,
            a=int(a),
            b=int(b),
        )
        record = await result.single()
    return {"connected": record["connected"] if record else False}


@app.get("/health")
async def health(request: Request):
    driver = request.app.state.neo4j
    async with driver.session() as session:
        r1 = await (await session.run("MATCH (a:Actor) RETURN count(a) AS n")).single()
        r2 = await (await session.run("MATCH (m:Movie) RETURN count(m) AS n")).single()
        r3 = await (await session.run("MATCH ()-[r:APPEARED_IN]->() RETURN count(r) AS n")).single()
    return {
        "status": "ok",
        "actors": r1["n"],
        "movies": r2["n"],
        "edges": r3["n"],
    }
