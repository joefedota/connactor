"""
Singleton graph store. Loaded once at server startup via FastAPI lifespan.

Holds:
  - G: NetworkX bipartite graph (actor + movie nodes)
  - actor_trie: Trie over actor names
  - movie_trie: Trie over movie titles
  - actor_index / movie_index: raw item lists (for neighbor-constrained search)
  - eligible_actors: top-N actor IDs ranked by aggregate filmography vote count
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from app.autocomplete import Trie, build_trie

TOP_ACTORS = 5000


@dataclass
class GraphStore:
    graph: nx.Graph
    actor_trie: Trie
    movie_trie: Trie
    actor_index: list[dict]  # [{id, label, type}, ...]
    movie_index: list[dict]
    eligible_actors: list[str]  # top-N actor IDs by aggregate vote score


_store: GraphStore | None = None


def _build_eligible_actors(G: nx.Graph, movie_index: list[dict], top_n: int) -> list[str]:
    vote_by_id = {m["id"]: m.get("votes", 0) for m in movie_index}
    scores: list[tuple[int, str]] = []
    for node_id, data in G.nodes(data=True):
        if data.get("type") != "actor":
            continue
        score = sum(vote_by_id.get(nbr, 0) for nbr in G.neighbors(node_id))
        scores.append((score, node_id))
    scores.sort(reverse=True)
    return [nconst for _, nconst in scores[:top_n]]


def load_store(processed_dir: Path) -> GraphStore:
    global _store

    graph_path = processed_dir / "graph.pkl"
    actor_path = processed_dir / "actor_index.json"
    movie_path = processed_dir / "movie_index.json"

    print(f"Loading graph from {graph_path} ...")
    with open(graph_path, "rb") as f:
        G: nx.Graph = pickle.load(f)
    print(f"  {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

    with open(actor_path) as f:
        actor_index: list[dict] = json.load(f)
    with open(movie_path) as f:
        movie_index: list[dict] = json.load(f)

    print(f"Building tries ({len(actor_index):,} actors, {len(movie_index):,} movies) ...")
    actor_trie = build_trie(actor_index, label_key="label")
    movie_trie = build_trie(movie_index, label_key="label")

    patches_path = processed_dir.parent / "patches.json"
    if patches_path.exists():
        with open(patches_path) as f:
            patches = json.load(f)
        for p in patches:
            a, m = p["actor_nconst"], p["movie_tconst"]
            if a in G and m in G and not G.has_edge(a, m):
                G.add_edge(a, m)
                print(f"  Patched edge: {G.nodes[a]['name']} ↔ {G.nodes[m]['title']}")

    print(f"Ranking top {TOP_ACTORS} eligible actors by vote score ...")
    eligible_actors = _build_eligible_actors(G, movie_index, TOP_ACTORS)
    print(f"  Eligible pool: {len(eligible_actors)} actors")

    _store = GraphStore(
        graph=G,
        actor_trie=actor_trie,
        movie_trie=movie_trie,
        actor_index=actor_index,
        movie_index=movie_index,
        eligible_actors=eligible_actors,
    )
    print("Graph store ready.")
    return _store


def get_store() -> GraphStore:
    if _store is None:
        raise RuntimeError("Graph store not loaded. Call load_store() first.")
    return _store
