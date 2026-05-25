"""
FastAPI backend for Connactor.

Endpoints:
  GET  /game                                    — random actor pair
  POST /validate                                — validate user's current path
  POST /solve                                   — all optimal paths (give up / end)
  GET  /autocomplete?q=...&type=actor|movie     — prefix search (unconstrained)
  GET  /autocomplete/neighbors?node_id=...&type=actor|movie  — neighbors of a node
  GET  /connected?a=...&b=...                   — edge existence check
  GET  /daily                                   — today's daily challenge puzzle
  POST /complete                                — record any game completion
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import time
import uuid  # used in /game for ephemeral game_id
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from neo4j.exceptions import ClientError
from sqlalchemy import text

from app.db import get_driver
from app.middleware.user_identity import UserIdentityMiddleware
from app.pg import get_session
from app.models import (
    AutocompleteResponse,
    CompleteRequest,
    CompleteResponse,
    CompletionInfo,
    DailyResponse,
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


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Connactor API", lifespan=lifespan)


@app.middleware("http")
async def _log_request_timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    logger.info("TIMING %s %s %d %.0fms", request.method, request.url.path, response.status_code, ms)
    return response

app.add_middleware(UserIdentityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://connactor.com", "https://www.connactor.com"],
    allow_credentials=True,
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

    t0 = time.perf_counter()
    async with driver.session() as session:
        # Pick two random actors from the difficulty's rank tier in one indexed query,
        # then verify a path exists between them (capped at 12 hops). Most popular pairs
        # are 2-4 hops apart so this resolves in a single attempt; retry only if we
        # happen to pick a disconnected pair.
        for attempt in range(MAX_GAME_ATTEMPTS):
            t1 = time.perf_counter()
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
            logger.info("TIMING /game attempt=%d neo4j=%.0fms", attempt + 1, (time.perf_counter() - t1) * 1000)
            if record is None:
                continue

            source = record["source"]
            target = record["target"]
            logger.info("TIMING /game total=%.0fms difficulty=%s", (time.perf_counter() - t0) * 1000, difficulty)
            return GameResponse(
                game_id=str(uuid.uuid4()),
                source=NodeInfo(
                    type="actor",
                    id=str(source["person_id"]),
                    label=source["name"],
                    popularity=source.get("popularity"),
                    image_path=source.get("profile_path"),
                ),
                target=NodeInfo(
                    type="actor",
                    id=str(target["person_id"]),
                    label=target["name"],
                    popularity=target.get("popularity"),
                    image_path=target.get("profile_path"),
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
                "MATCH (a:Actor {person_id: $id}) RETURN a.name AS name, a.popularity AS popularity, a.profile_path AS profile_path",
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
            image_path=record.get("profile_path"),
        )
        return SolveResponse(hop_count=0, paths=[[node]])

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH p = allShortestPaths(
                (a1:Actor {person_id: $source})-[:APPEARED_IN*..12]-(a2:Actor {person_id: $target})
            )
            WHERE all(n IN nodes(p) WHERE 'Actor' IN labels(n)
              OR (coalesce(n.vote_count, 0) >= 100 AND NOT 99 IN coalesce(n.genre_ids, [])))
            RETURN [n IN nodes(p) | CASE labels(n)[0]
                WHEN 'Actor' THEN {type: 'actor', id: toString(n.person_id), label: n.name,  popularity: n.popularity, image_path: n.profile_path, fame_rank: n.fame_rank}
                WHEN 'Movie' THEN {type: 'movie', id: toString(n.movie_id),  label: n.title, year: toString(n.year), image_path: n.poster_path}
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
    # Sort paths by average fame_rank of intermediate actors ascending (lower rank = more famous).
    # Intermediate actors = all actors except the first and last in the path.
    def _path_fame_key(path: list[NodeInfo]) -> float:
        intermediate = [n for n in path[1:-1] if n.type == "actor"]
        if not intermediate:
            return 0.0
        ranks = [n.fame_rank for n in intermediate if n.fame_rank is not None]
        return sum(ranks) / len(ranks) if ranks else float("inf")

    paths.sort(key=_path_fame_key)
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

    t0 = time.perf_counter()
    async with driver.session() as session:
        try:
            if type == "actor":
                result = await session.run(
                    """
                    CALL db.index.fulltext.queryNodes('actorNames', $search)
                    YIELD node, score
                    RETURN node.person_id AS id, node.name AS label,
                           node.popularity AS popularity, node.profile_path AS image_path
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
                           node.year AS year, node.vote_count AS vote_count,
                           node.poster_path AS image_path
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
    logger.info("TIMING /autocomplete type=%s neo4j=%.0fms", type, (time.perf_counter() - t0) * 1000)

    results = []
    for rec in records:
        if type == "actor":
            results.append(NodeInfo(
                type="actor",
                id=str(rec["id"]),
                label=rec["label"],
                popularity=rec.get("popularity"),
                image_path=rec.get("image_path"),
            ))
        else:
            results.append(NodeInfo(
                type="movie",
                id=str(rec["id"]),
                label=rec["label"],
                year=str(rec["year"]) if rec.get("year") else None,
                image_path=rec.get("image_path"),
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

    t0 = time.perf_counter()
    async with driver.session() as session:
        if type == "actor":
            # node_id is a movie — fetch its actors
            cypher = """
                MATCH (m:Movie {movie_id: $node_id})<-[:APPEARED_IN]-(a:Actor)
                WHERE $q = '' OR toLower(a.name) CONTAINS toLower($q)
                RETURN a.person_id AS id, a.name AS label, a.popularity AS popularity,
                       a.profile_path AS image_path
                ORDER BY a.popularity DESC
                LIMIT $limit
            """
        else:
            # node_id is an actor — fetch their movies
            cypher = """
                MATCH (a:Actor {person_id: $node_id})-[:APPEARED_IN]->(m:Movie)
                WHERE $q = '' OR toLower(m.title) CONTAINS toLower($q)
                RETURN m.movie_id AS id, m.title AS label, m.year AS year, m.vote_count AS vote_count,
                       m.poster_path AS image_path
                ORDER BY m.vote_count DESC
                LIMIT $limit
            """
        result = await session.run(cypher, node_id=int(node_id), q=q, limit=limit)
        records = await result.data()
    logger.info("TIMING /autocomplete/neighbors type=%s neo4j=%.0fms", type, (time.perf_counter() - t0) * 1000)

    results = []
    for rec in records:
        if type == "actor":
            results.append(NodeInfo(
                type="actor",
                id=str(rec["id"]),
                label=rec["label"],
                popularity=rec.get("popularity"),
                image_path=rec.get("image_path"),
            ))
        else:
            results.append(NodeInfo(
                type="movie",
                id=str(rec["id"]),
                label=rec["label"],
                year=str(rec["year"]) if rec.get("year") else None,
                image_path=rec.get("image_path"),
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


async def _fetch_actor_node(driver, person_id: int) -> NodeInfo:
    async with driver.session() as session:
        result = await session.run(
            "MATCH (a:Actor {person_id: $id}) RETURN a",
            id=person_id,
        )
        record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail=f"Actor {person_id} not found.")
    node = record["a"]
    return NodeInfo(
        type="actor",
        id=str(node["person_id"]),
        label=node["name"],
        popularity=node.get("popularity"),
        image_path=node.get("profile_path"),
    )


async def _compute_streak(session, user_id: str) -> int:
    """Count consecutive daily completions ending today or yesterday (UTC).

    Counts from yesterday when today hasn't been played yet so the streak
    doesn't drop to 0 mid-day.
    """
    rows = await session.execute(
        text(
            """
            SELECT p.scheduled_date
            FROM game_completions gc
            JOIN puzzles p ON p.puzzle_id = gc.puzzle_id
            WHERE gc.user_id = :uid
              AND p.is_daily = TRUE
              AND p.scheduled_date IS NOT NULL
            ORDER BY p.scheduled_date DESC
            """
        ),
        {"uid": user_id},
    )
    dates = [row[0] for row in rows]
    if not dates:
        return 0

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    # If the most recent play was before yesterday the streak is broken.
    if dates[0] not in (today, yesterday):
        return 0

    streak = 0
    expected = dates[0]
    for d in dates:
        if d == expected:
            streak += 1
            expected -= datetime.timedelta(days=1)
        else:
            break
    return streak


async def _get_completion_and_streak(user_id: str, puzzle_id: str) -> tuple:
    """Fetch completion record and streak in a single Postgres session."""
    async with get_session() as session:
        comp_row = await session.execute(
            text(
                """
                SELECT hops, time_ms, completed_at
                FROM game_completions
                WHERE user_id = :uid AND puzzle_id = :pid
                """
            ),
            {"uid": user_id, "pid": puzzle_id},
        )
        comp = comp_row.first()
        streak = await _compute_streak(session, user_id)
    return comp, streak


@app.get("/daily", response_model=DailyResponse)
async def get_daily(request: Request):
    today = datetime.date.today()
    driver = request.app.state.neo4j
    user_id: str = request.state.user_id

    t0 = time.perf_counter()
    async with get_session() as session:
        row = await session.execute(
            text(
                """
                SELECT puzzle_id, source_id, target_id, optimal_hops
                FROM puzzles
                WHERE is_daily = TRUE AND scheduled_date = :today
                """
            ),
            {"today": today},
        )
        puzzle = row.first()
    logger.info("TIMING /daily pg_puzzle=%.0fms", (time.perf_counter() - t0) * 1000)

    if not puzzle:
        raise HTTPException(status_code=404, detail="No daily puzzle available yet.")

    puzzle_id = str(puzzle.puzzle_id)

    # Neo4j actor fetches and Postgres completion+streak run in parallel.
    t1 = time.perf_counter()
    (source_node, target_node), (comp, streak) = await asyncio.gather(
        asyncio.gather(
            _fetch_actor_node(driver, puzzle.source_id),
            _fetch_actor_node(driver, puzzle.target_id),
        ),
        _get_completion_and_streak(user_id, puzzle_id),
    )
    logger.info("TIMING /daily parallel(neo4j+pg_completion)=%.0fms", (time.perf_counter() - t1) * 1000)

    return DailyResponse(
        puzzle_date=today.isoformat(),
        puzzle_id=puzzle_id,
        source=source_node,
        target=target_node,
        optimal_hops=puzzle.optimal_hops,
        already_completed=comp is not None,
        completion=CompletionInfo(
            hops=comp.hops,
            time_ms=comp.time_ms,
            completed_at=comp.completed_at.isoformat(),
        ) if comp else None,
        current_streak=streak,
    )


@app.post("/complete", response_model=CompleteResponse)
async def post_complete(request: Request, body: CompleteRequest):
    user_id: str = request.state.user_id

    if body.puzzle_id is None:
        if body.source_id is None or body.target_id is None or body.optimal_hops is None:
            raise HTTPException(
                status_code=422,
                detail="source_id, target_id, and optimal_hops are required when puzzle_id is not provided.",
            )

    async with get_session() as session:
        if body.puzzle_id:
            pid_row = await session.execute(
                text("SELECT puzzle_id FROM puzzles WHERE puzzle_id = :pid"),
                {"pid": body.puzzle_id},
            )
            if not pid_row.first():
                raise HTTPException(status_code=404, detail="Puzzle not found.")
            puzzle_id = body.puzzle_id
        else:
            await session.execute(
                text(
                    """
                    INSERT INTO puzzles (source_id, target_id, optimal_hops)
                    VALUES (:src, :tgt, :hops)
                    ON CONFLICT (source_id, target_id) DO NOTHING
                    """
                ),
                {"src": int(body.source_id), "tgt": int(body.target_id), "hops": body.optimal_hops},
            )
            pid_row = await session.execute(
                text("SELECT puzzle_id FROM puzzles WHERE source_id = :src AND target_id = :tgt"),
                {"src": int(body.source_id), "tgt": int(body.target_id)},
            )
            puzzle_id = str(pid_row.scalar_one())

        existing = await session.execute(
            text(
                """
                SELECT completion_id, hops, time_ms, completed_at
                FROM game_completions
                WHERE user_id = :uid AND puzzle_id = :pid
                """
            ),
            {"uid": user_id, "pid": puzzle_id},
        )
        existing_row = existing.first()
        if existing_row:
            await session.commit()
            return CompleteResponse(
                completion_id=str(existing_row.completion_id),
                puzzle_id=puzzle_id,
                hops=existing_row.hops,
                time_ms=existing_row.time_ms,
                completed_at=existing_row.completed_at.isoformat(),
            )

        new_row = await session.execute(
            text(
                """
                INSERT INTO game_completions (user_id, puzzle_id, hops, time_ms)
                VALUES (:uid, :pid, :hops, :time_ms)
                RETURNING completion_id, completed_at
                """
            ),
            {"uid": user_id, "pid": puzzle_id, "hops": body.hops, "time_ms": body.time_ms},
        )
        inserted = new_row.first()
        await session.commit()

    return CompleteResponse(
        completion_id=str(inserted.completion_id),
        puzzle_id=puzzle_id,
        hops=body.hops,
        time_ms=body.time_ms,
        completed_at=inserted.completed_at.isoformat(),
    )
