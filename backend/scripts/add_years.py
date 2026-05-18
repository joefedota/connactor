#!/usr/bin/env python3
"""
One-time script to patch year onto movie nodes in graph.pkl
and rebuild movie_index.json. Run instead of a full re-ingest.
"""
import gzip
import json
import pickle
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

print("Loading graph...")
with open(PROCESSED_DIR / "graph.pkl", "rb") as f:
    import networkx as nx
    G = nx.Graph()
    G = pickle.load(f)

print("Loading years from title.basics...")
years: dict = {}
with gzip.open(RAW_DIR / "title.basics.tsv.gz", "rt", encoding="utf-8") as f:
    header = f.readline().strip().split("\t")
    ti = header.index("tconst")
    yi = header.index("startYear")
    for line in f:
        p = line.rstrip("\n").split("\t")
        years[p[ti]] = None if p[yi] == "\\N" else p[yi]

print("Patching year onto movie nodes...")
patched = 0
for node_id, data in G.nodes(data=True):
    if data.get("type") == "movie":
        yr = years.get(node_id)
        data["year"] = yr
        patched += 1
print(f"  Patched {patched:,} movie nodes")

print("Saving graph.pkl...")
with open(PROCESSED_DIR / "graph.pkl", "wb") as f:
    pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)

print("Loading vote counts...")
with open(PROCESSED_DIR / "movie_index.json") as f:
    old_index = json.load(f)
vote_by_id = {m["id"]: m.get("votes", 0) for m in old_index}

print("Rebuilding movie_index.json with year...")
movies = [
    {
        "id": n,
        "label": d["title"],
        "year": d.get("year"),
        "type": "movie",
        "votes": vote_by_id.get(n, 0),
    }
    for n, d in G.nodes(data=True)
    if d.get("type") == "movie"
]
movies.sort(key=lambda x: x["votes"], reverse=True)
with open(PROCESSED_DIR / "movie_index.json", "w") as f:
    json.dump(movies, f)
print(f"  Wrote {len(movies):,} movies")

print("Done. Restart the backend.")
