"""
FastAPI backend for Connactor.

Endpoints:
  GET  /game                                    — random actor pair
  POST /validate                                — validate user's current path
  POST /solve                                   — all optimal paths (give up / end)
  GET  /autocomplete?q=...&type=actor|movie     — prefix search (unconstrained)
  GET  /autocomplete/neighbors?node_id=...&type=actor|movie  — neighbors of a node
"""
from __future__ import annotations

import random
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.bfs import (
    bfs_shortest_path_length,
    find_all_shortest_paths,
    neighbors_of_type,
    path_to_display,
    validate_path,
)
from app.autocomplete import filter_neighbors, query_autocomplete
from app.graph_store import GraphStore, get_store, load_store
from app.models import (
    AutocompleteResponse,
    GameResponse,
    NodeInfo,
    SolveRequest,
    SolveResponse,
    ValidateRequest,
    ValidateResponse,
)

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_store(PROCESSED_DIR)
    yield


app = FastAPI(title="Connactor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


MAX_GAME_ATTEMPTS = 50
MIN_HOPS = 2
MAX_HOPS = 6


def classify_difficulty(G, source_id: str, target_id: str, hops: int) -> str:
    """Classify game difficulty based on path length and actor popularity."""
    P_source = G.nodes[source_id].get("popularity", 0.0)
    P_target = G.nodes[target_id].get("popularity", 0.0)
    P_min = min(P_source, P_target)

    if hops == 2 and P_min >= 5.0:
        return "easy"
    elif hops <= 4 and P_min >= 4.0:
        return "medium"
    elif hops <= 6 and P_min >= 3.0:
        return "hard"
    else:
        return "expert"


@app.get("/game", response_model=GameResponse)
def get_game(
    difficulty: Optional[str] = Query(
        None, pattern="^(easy|medium|hard|expert)$"
    )
):
    """
    Pick two random eligible actors with a valid 2-6 hop path via live BFS,
    optionally filtering to a requested difficulty.
    """
    store = get_store()
    G = store.graph
    pool = store.eligible_actors

    fallback_pair = None
    fallback_diff = None

    for _ in range(MAX_GAME_ATTEMPTS):
        source_id, target_id = random.sample(pool, 2)
        hops = bfs_shortest_path_length(G, source_id, target_id)
        if hops is not None and MIN_HOPS <= hops <= MAX_HOPS:
            diff = classify_difficulty(G, source_id, target_id, hops)
            if difficulty is None or diff == difficulty:
                return GameResponse(
                    game_id=str(uuid.uuid4()),
                    source=NodeInfo(
                        type="actor",
                        id=source_id,
                        label=G.nodes[source_id]["name"],
                        popularity=G.nodes[source_id].get("popularity"),
                    ),
                    target=NodeInfo(
                        type="actor",
                        id=target_id,
                        label=G.nodes[target_id]["name"],
                        popularity=G.nodes[target_id].get("popularity"),
                    ),
                    difficulty=diff,
                )
            if fallback_pair is None:
                fallback_pair = (source_id, target_id)
                fallback_diff = diff

    # If we requested a specific difficulty and didn't find one in 50 tries,
    # but found at least one valid pair, fall back to it gracefully
    if fallback_pair is not None:
        source_id, target_id = fallback_pair
        return GameResponse(
            game_id=str(uuid.uuid4()),
            source=NodeInfo(
                type="actor",
                id=source_id,
                label=G.nodes[source_id]["name"],
                popularity=G.nodes[source_id].get("popularity"),
            ),
            target=NodeInfo(
                type="actor",
                id=target_id,
                label=G.nodes[target_id]["name"],
                popularity=G.nodes[target_id].get("popularity"),
            ),
            difficulty=fallback_diff,
        )

    raise HTTPException(status_code=503, detail="Could not find a valid pair. Try again.")


@app.post("/validate", response_model=ValidateResponse)
def post_validate(body: ValidateRequest):
    """
    Validate the user's in-progress path.
    Returns is_complete=True when path[-1] == target and path is valid.
    Returns is_optimal=True when completed path length equals BFS minimum.
    """
    store = get_store()
    G = store.graph

    if body.source_nconst not in G:
        raise HTTPException(status_code=400, detail=f"Unknown source: {body.source_nconst}")
    if body.target_nconst not in G:
        raise HTTPException(status_code=400, detail=f"Unknown target: {body.target_nconst}")

    valid, error = validate_path(G, body.path, body.source_nconst, body.target_nconst)
    if not valid:
        return ValidateResponse(valid=False, error=error)

    is_complete = len(body.path) >= 3 and body.path[-1] == body.target_nconst
    is_optimal: Optional[bool] = None
    if is_complete:
        min_hops = bfs_shortest_path_length(G, body.source_nconst, body.target_nconst)
        player_hops = len(body.path) - 1  # edge count
        is_optimal = (min_hops is not None and player_hops == min_hops)

    return ValidateResponse(
        valid=True,
        is_complete=is_complete,
        is_optimal=is_optimal,
    )


@app.post("/solve", response_model=SolveResponse)
def post_solve(body: SolveRequest):
    """Return all optimal paths between source and target (up to 10)."""
    store = get_store()
    G = store.graph

    if body.source_nconst not in G:
        raise HTTPException(status_code=400, detail=f"Unknown source: {body.source_nconst}")
    if body.target_nconst not in G:
        raise HTTPException(status_code=400, detail=f"Unknown target: {body.target_nconst}")

    hop_count = bfs_shortest_path_length(G, body.source_nconst, body.target_nconst)
    if hop_count is None:
        raise HTTPException(status_code=404, detail="No path exists between these actors.")

    raw_paths = find_all_shortest_paths(G, body.source_nconst, body.target_nconst)
    display_paths = [
        [NodeInfo(**node) for node in path_to_display(G, p)]
        for p in raw_paths
    ]
    return SolveResponse(hop_count=hop_count, paths=display_paths)


@app.get("/autocomplete", response_model=AutocompleteResponse)
def get_autocomplete(
    q: str = Query(..., min_length=2),
    type: str = Query(..., pattern="^(actor|movie)$"),
    limit: int = Query(10, ge=1, le=20),
):
    """Unconstrained prefix search over all actors or all movies."""
    store = get_store()
    trie = store.actor_trie if type == "actor" else store.movie_trie
    results = query_autocomplete(trie, q, limit * 3)  # fetch extra, then sort

    if type == "actor":
        results.sort(key=lambda r: r.get("popularity", 0.0), reverse=True)
    else:
        results.sort(key=lambda r: r.get("votes", 0), reverse=True)

    return AutocompleteResponse(
        results=[
            NodeInfo(
                type=r["type"],
                id=r["id"],
                label=r["label"],
                year=r.get("year"),
                popularity=r.get("popularity"),
            )
            for r in results[:limit]
        ]
    )


@app.get("/autocomplete/neighbors", response_model=AutocompleteResponse)
def get_autocomplete_neighbors(
    node_id: str = Query(...),
    type: str = Query(..., pattern="^(actor|movie)$"),
    q: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Return neighbors of node_id filtered to the given type.
    Optionally filter by prefix q for further narrowing.
    Used by the game board: after selecting an actor, fetch their movies;
    after selecting a movie, fetch other actors in it.
    """
    store = get_store()
    G = store.graph

    if node_id not in G:
        raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}")

    neighbor_ids = set(neighbors_of_type(G, node_id, type))
    index = store.actor_index if type == "actor" else store.movie_index
    candidates = filter_neighbors(index, neighbor_ids)

    if q and len(q) >= 2:
        trie = store.actor_trie if type == "actor" else store.movie_trie
        matched = query_autocomplete(trie, q, limit * 5)
        matched_ids = {m["id"] for m in matched}
        candidates = [c for c in candidates if c["id"] in matched_ids]

    if type == "actor":
        candidates.sort(key=lambda x: x.get("popularity", 0.0), reverse=True)
    else:
        candidates.sort(key=lambda x: x.get("votes", 0), reverse=True)

    return AutocompleteResponse(
        results=[
            NodeInfo(
                type=c["type"],
                id=c["id"],
                label=c["label"],
                year=c.get("year"),
                popularity=c.get("popularity"),
            )
            for c in candidates[:limit]
        ]
    )


@app.get("/connected")
def get_connected(a: str = Query(...), b: str = Query(...)):
    """Check whether two nodes share an edge in the graph."""
    store = get_store()
    G = store.graph
    if a not in G or b not in G:
        raise HTTPException(status_code=404, detail="Unknown node ID")
    return {"connected": G.has_edge(a, b)}


@app.get("/health")
def health():
    store = get_store()
    return {
        "status": "ok",
        "nodes": store.graph.number_of_nodes(),
        "edges": store.graph.number_of_edges(),
        "eligible_actors": len(store.eligible_actors),
    }
