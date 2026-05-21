#!/usr/bin/env python3
"""
Download and parse IMDB bulk TSV dumps, build a NetworkX bipartite graph,
and write graph.pkl + actor_index.json + movie_index.json to data/processed/.

Run once (or whenever IMDB data refreshes):
    python3 scripts/ingest.py

Downloads ~1 GB of raw data. Requires ~2 GB RAM to build the graph.
"""
from __future__ import annotations

import gzip
import json
import math
import pickle
import urllib.request
from pathlib import Path

import networkx as nx

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

IMDB_BASE = "https://datasets.imdbws.com"
IMDB_FILES = [
    "title.basics.tsv.gz",
    "title.principals.tsv.gz",
    "name.basics.tsv.gz",
    "title.ratings.tsv.gz",
]

MIN_CREDITS = 5
VALID_CATEGORIES = {"actor", "actress"}


def download_imdb_files() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for filename in IMDB_FILES:
        dest = RAW_DIR / filename
        if dest.exists():
            print(f"  {filename} already exists, skipping")
            continue
        url = f"{IMDB_BASE}/{filename}"
        print(f"  Downloading {filename} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"  Saved to {dest}")


def load_title_basics(path: Path) -> dict[str, dict]:
    """Return tconst→{title, year} for titleType=movie only."""
    titles: dict[str, dict] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_tconst = header.index("tconst")
        idx_type = header.index("titleType")
        idx_title = header.index("primaryTitle")
        idx_year = header.index("startYear")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if parts[idx_type] != "movie":
                continue
            year = parts[idx_year]
            titles[parts[idx_tconst]] = {
                "title": parts[idx_title],
                "year": None if year == "\\N" else year,
            }
    print(f"  Loaded {len(titles):,} movies")
    return titles


def load_actor_credits(path: Path, valid_tconsts: set[str]) -> dict[str, list[str]]:
    """Return nconst→[tconst, ...] for actors with >= MIN_CREDITS qualifying movies."""
    credits: dict[str, list[str]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_tconst = header.index("tconst")
        idx_nconst = header.index("nconst")
        idx_category = header.index("category")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            tconst = parts[idx_tconst]
            if tconst not in valid_tconsts:
                continue
            if parts[idx_category] not in VALID_CATEGORIES:
                continue
            credits.setdefault(parts[idx_nconst], []).append(tconst)

    filtered = {n: t for n, t in credits.items() if len(t) >= MIN_CREDITS}
    print(f"  Loaded {len(filtered):,} actors (>= {MIN_CREDITS} credits) from {len(credits):,} total")
    return filtered


def load_name_metadata(path: Path, valid_nconsts: set[str]) -> dict[str, dict]:
    """Return nconst→{name, birth_year} for actors in valid_nconsts."""
    metadata: dict[str, dict] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_nconst = header.index("nconst")
        idx_name = header.index("primaryName")
        idx_birth = header.index("birthYear")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            nconst = parts[idx_nconst]
            if nconst not in valid_nconsts:
                continue
            birth = parts[idx_birth]
            metadata[nconst] = {
                "name": parts[idx_name],
                "birth_year": None if birth == "\\N" else birth,
            }
    print(f"  Loaded metadata for {len(metadata):,} actors")
    return metadata


def build_graph(
    credits: dict[str, list[str]],
    actor_metadata: dict[str, dict],
    movie_titles: dict[str, dict],
) -> nx.Graph:
    G = nx.Graph()
    for nconst, meta in actor_metadata.items():
        G.add_node(nconst, type="actor", name=meta["name"], birth_year=meta.get("birth_year"))
    seen_movies: set[str] = set()
    for nconst, tconsts in credits.items():
        if nconst not in actor_metadata:
            continue
        for tconst in tconsts:
            if tconst not in seen_movies:
                info = movie_titles.get(tconst, {"title": "Unknown", "year": None})
                G.add_node(tconst, type="movie", title=info["title"], year=info.get("year"))
                seen_movies.add(tconst)
            G.add_edge(nconst, tconst)
    print(f"  Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")
    return G


def calculate_actor_popularity(G: nx.Graph, vote_counts: dict[str, int]) -> None:
    """Compute a popularity score (0.0 to 10.0) for every actor based on filmography votes."""
    for node_id, data in G.nodes(data=True):
        if data.get("type") != "actor":
            continue
        # Get vote counts for all movie neighbors
        movie_votes = [vote_counts.get(nbr, 0) for nbr in G.neighbors(node_id)]
        if not movie_votes:
            data["popularity"] = 0.0
            continue
        # Take average of top 3 highest-voted movies
        movie_votes.sort(reverse=True)
        top_3 = movie_votes[:3]
        avg_votes = sum(top_3) / len(top_3)
        # Logarithmic popularity rating
        data["popularity"] = round(math.log10(avg_votes + 1), 2)


def build_actor_index(G: nx.Graph) -> list[dict]:
    actors = [
        {"id": n, "label": d["name"], "type": "actor", "popularity": d.get("popularity", 0.0)}
        for n, d in G.nodes(data=True)
        if d.get("type") == "actor"
    ]
    actors.sort(key=lambda x: x["label"].lower())
    return actors


def load_vote_counts(path: Path) -> dict[str, int]:
    """Return tconst→numVotes for all rated titles."""
    votes: dict[str, int] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        f.readline()  # skip header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            try:
                votes[parts[0]] = int(parts[2])
            except (IndexError, ValueError):
                pass
    print(f"  Loaded vote counts for {len(votes):,} titles")
    return votes


def build_movie_index(G: nx.Graph, vote_counts: dict[str, int]) -> list[dict]:
    movies = [
        {
            "id": n,
            "label": d["title"],
            "year": d.get("year"),
            "type": "movie",
            "votes": vote_counts.get(n, 0),
        }
        for n, d in G.nodes(data=True)
        if d.get("type") == "movie"
    ]
    movies.sort(key=lambda x: x["votes"], reverse=True)
    return movies


def main() -> None:
    print("=== Connactor IMDB Ingest ===")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/5] Downloading IMDB dumps...")
    download_imdb_files()

    print("\n[2/5] Loading title basics...")
    movie_titles = load_title_basics(RAW_DIR / "title.basics.tsv.gz")

    print("\n[3/5] Loading actor credits...")
    credits = load_actor_credits(RAW_DIR / "title.principals.tsv.gz", set(movie_titles.keys()))

    print("\n[4/5] Loading name metadata...")
    actor_metadata = load_name_metadata(RAW_DIR / "name.basics.tsv.gz", set(credits.keys()))

    print("\n[5/5] Building graph...")
    G = build_graph(credits, actor_metadata, movie_titles)

    print("\nLoading vote counts and calculating popularity...")
    vote_counts = load_vote_counts(RAW_DIR / "title.ratings.tsv.gz")
    calculate_actor_popularity(G, vote_counts)

    graph_path = PROCESSED_DIR / "graph.pkl"
    with open(graph_path, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  Wrote {graph_path}")

    actor_index = build_actor_index(G)
    with open(PROCESSED_DIR / "actor_index.json", "w") as f:
        json.dump(actor_index, f)
    print(f"  Wrote actor_index.json ({len(actor_index):,} actors)")

    movie_index = build_movie_index(G, vote_counts)
    with open(PROCESSED_DIR / "movie_index.json", "w") as f:
        json.dump(movie_index, f)
    print(f"  Wrote movie_index.json ({len(movie_index):,} movies)")

    print("\nDone. Run generate_pairs.py next.")



if __name__ == "__main__":
    main()
