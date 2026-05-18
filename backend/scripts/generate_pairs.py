#!/usr/bin/env python3
"""
Sample random actor pairs, run BFS to find shortest path length,
and write 1000 valid pairs to data/processed/pairs.json.

Run after ingest.py:
    python scripts/generate_pairs.py

Starting actors are filtered to those who appeared in at least one movie
with >= MIN_VOTES IMDB votes. The full graph (all actors/movies) is still
used for BFS — this only affects which actors can be puzzle endpoints.

Pair criteria:
  - Both actors have >= 1 movie with >= MIN_VOTES votes
  - Connected (path exists)
  - Shortest path 2-6 hops
"""
from __future__ import annotations

import gzip
import json
import pickle
import random
from collections import deque
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

TARGET_PAIRS = 1000
MAX_HOPS = 6
MIN_HOPS = 2
TOP_ACTORS = 100     # only sample pairs from the top N actors by aggregate vote count
SAMPLE_BATCH = 50    # smaller batch since pool is only 100


def load_vote_counts(ratings_path: Path) -> dict[str, int]:
    """Return tconst→numVotes for all rated movies."""
    votes: dict[str, int] = {}
    with gzip.open(ratings_path, "rt", encoding="utf-8") as f:
        f.readline()  # skip header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            votes[parts[0]] = int(parts[2])
    print(f"  Loaded vote counts for {len(votes):,} titles")
    return votes


def bfs_length(G, source: str, target: str):
    if source == target:
        return 0
    visited = {source}
    queue = deque([(source, 0)])
    while queue:
        node, depth = queue.popleft()
        for neighbor in G.neighbors(node):
            if neighbor == target:
                return depth + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    return None


def main() -> None:
    import networkx as nx

    graph_path = PROCESSED_DIR / "graph.pkl"
    ratings_path = RAW_DIR / "title.ratings.tsv.gz"

    print("Loading graph...")
    with open(graph_path, "rb") as f:
        G: nx.Graph = pickle.load(f)

    print("Loading vote counts...")
    vote_counts = load_vote_counts(ratings_path)

    # Score each actor by total votes across their filmography, take top N
    print(f"Ranking actors by aggregate vote count, taking top {TOP_ACTORS}...")
    actor_scores: list[tuple[int, str]] = []
    for n, d in G.nodes(data=True):
        if d.get("type") != "actor":
            continue
        total = sum(vote_counts.get(nb, 0) for nb in G.neighbors(n))
        actor_scores.append((total, n))

    actor_scores.sort(reverse=True)
    eligible_actors = [nconst for _, nconst in actor_scores[:TOP_ACTORS]]
    print(f"  Top actor: {G.nodes[eligible_actors[0]]['name']} ({actor_scores[0][0]:,} total votes)")
    print(f"  #500:      {G.nodes[eligible_actors[-1]]['name']} ({actor_scores[TOP_ACTORS-1][0]:,} total votes)")

    pairs: list[dict] = []
    attempts = 0

    print(f"Sampling pairs (target: {TARGET_PAIRS})...")
    while len(pairs) < TARGET_PAIRS:
        batch = random.sample(eligible_actors, min(SAMPLE_BATCH, len(eligible_actors)))
        for i in range(0, len(batch) - 1, 2):
            source, target = batch[i], batch[i + 1]
            attempts += 1
            hops = bfs_length(G, source, target)
            if hops is None or hops < MIN_HOPS or hops > MAX_HOPS:
                continue
            pairs.append({
                "source_nconst": source,
                "source_name": G.nodes[source]["name"],
                "target_nconst": target,
                "target_name": G.nodes[target]["name"],
                "hop_count": hops,
            })
            if len(pairs) % 100 == 0:
                print(f"  {len(pairs)}/{TARGET_PAIRS} pairs ({attempts:,} attempts)")
            if len(pairs) >= TARGET_PAIRS:
                break

    from collections import Counter
    print(f"\nGenerated {len(pairs)} pairs in {attempts:,} attempts")
    print(f"Accept rate: {len(pairs)/attempts*100:.1f}%")
    dist = Counter(p["hop_count"] for p in pairs)
    for hops in sorted(dist):
        print(f"  {hops} hops: {dist[hops]} pairs")

    out_path = PROCESSED_DIR / "pairs.json"
    with open(out_path, "w") as f:
        json.dump(pairs, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
