#!/usr/bin/env python3
"""
Debug tool to check whether an actor appears in the cast list of a movie,
checking both the processed graph and the original raw IMDB database.

Usage:
    uv run scripts/check_cast.py
    uv run scripts/check_cast.py --actor "Leonardo DiCaprio" --movie "Inception"
"""
from __future__ import annotations

import argparse
import gzip
import json
import pickle
import sys
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

MIN_CREDITS = 5
VALID_CATEGORIES = {"actor", "actress"}


def load_processed_data() -> tuple[any, list[dict], list[dict]]:
    graph_path = PROCESSED_DIR / "graph.pkl"
    actor_path = PROCESSED_DIR / "actor_index.json"
    movie_path = PROCESSED_DIR / "movie_index.json"

    G = None
    actor_index = []
    movie_index = []

    if graph_path.exists():
        print("Loading graph.pkl...")
        try:
            with open(graph_path, "rb") as f:
                G = pickle.load(f)
        except Exception as e:
            print(f"  Warning: Could not load graph.pkl: {e}")
    
    if actor_path.exists():
        print("Loading actor_index.json...")
        try:
            with open(actor_path) as f:
                actor_index = json.load(f)
        except Exception as e:
            print(f"  Warning: Could not load actor_index.json: {e}")

    if movie_path.exists():
        print("Loading movie_index.json...")
        try:
            with open(movie_path) as f:
                movie_index = json.load(f)
        except Exception as e:
            print(f"  Warning: Could not load movie_index.json: {e}")

    return G, actor_index, movie_index


def find_actor_in_raw(name_query: str) -> list[dict]:
    path = RAW_DIR / "name.basics.tsv.gz"
    if not path.exists():
        print(f"Error: Raw file {path} not found. Run ingestion first.")
        return []

    print(f"Searching raw {path.name} for actor matching '{name_query}'...")
    matches = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_nconst = header.index("nconst")
        idx_name = header.index("primaryName")
        idx_birth = header.index("birthYear")
        idx_profession = header.index("primaryProfession")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            name = parts[idx_name]
            if name_query.lower() in name.lower() or name_query == parts[idx_nconst]:
                # Check if actor/actress profession is listed (loose check)
                professions = parts[idx_profession]
                matches.append({
                    "id": parts[idx_nconst],
                    "name": name,
                    "birth_year": None if parts[idx_birth] == "\\N" else parts[idx_birth],
                    "professions": professions,
                    "type": "raw"
                })
                if len(matches) >= 10:
                    print("  (Found 10+ raw matches, truncating search...)")
                    break
    return matches


def find_movie_in_raw(title_query: str) -> list[dict]:
    path = RAW_DIR / "title.basics.tsv.gz"
    if not path.exists():
        print(f"Error: Raw file {path} not found. Run ingestion first.")
        return []

    print(f"Searching raw {path.name} for movie matching '{title_query}'...")
    matches = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_tconst = header.index("tconst")
        idx_type = header.index("titleType")
        idx_title = header.index("primaryTitle")
        idx_year = header.index("startYear")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            title = parts[idx_title]
            if title_query.lower() in title.lower() or title_query == parts[idx_tconst]:
                matches.append({
                    "id": parts[idx_tconst],
                    "title": title,
                    "title_type": parts[idx_type],
                    "year": None if parts[idx_year] == "\\N" else parts[idx_year],
                    "type": "raw"
                })
                if len(matches) >= 10:
                    print("  (Found 10+ raw matches, truncating search...)")
                    break
    return matches


def get_movie_raw_info(tconst: str) -> dict | None:
    path = RAW_DIR / "title.basics.tsv.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_tconst = header.index("tconst")
        idx_type = header.index("titleType")
        idx_title = header.index("primaryTitle")
        idx_year = header.index("startYear")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if parts[idx_tconst] == tconst:
                return {
                    "id": tconst,
                    "title": parts[idx_title],
                    "title_type": parts[idx_type],
                    "year": None if parts[idx_year] == "\\N" else parts[idx_year],
                }
    return None


def get_actor_raw_info(nconst: str) -> dict | None:
    path = RAW_DIR / "name.basics.tsv.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_nconst = header.index("nconst")
        idx_name = header.index("primaryName")
        idx_birth = header.index("birthYear")
        idx_profession = header.index("primaryProfession")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if parts[idx_nconst] == nconst:
                return {
                    "id": nconst,
                    "name": parts[idx_name],
                    "birth_year": None if parts[idx_birth] == "\\N" else parts[idx_birth],
                    "professions": parts[idx_profession],
                }
    return None


def scan_raw_principals_for_actor(nconst: str) -> list[dict]:
    path = RAW_DIR / "title.principals.tsv.gz"
    if not path.exists():
        return []
    print(f"Scanning raw principals list for actor {nconst} (this may take 10-15 seconds)...")
    credits = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_tconst = header.index("tconst")
        idx_nconst = header.index("nconst")
        idx_category = header.index("category")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if parts[idx_nconst] == nconst:
                credits.append({
                    "tconst": parts[idx_tconst],
                    "category": parts[idx_category]
                })
    return credits


def check_relationship_in_raw_principals(tconst: str, nconst: str) -> dict | None:
    path = RAW_DIR / "title.principals.tsv.gz"
    if not path.exists():
        return None
    print(f"Scanning raw principals list for specific link between {nconst} and {tconst}...")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        idx_tconst = header.index("tconst")
        idx_nconst = header.index("nconst")
        idx_category = header.index("category")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if parts[idx_tconst] == tconst and parts[idx_nconst] == nconst:
                return {
                    "category": parts[idx_category]
                }
    return None


def select_item(matches: list[dict], query_name: str, item_type: str) -> dict | None:
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    print(f"\nMultiple raw/processed matches found for {item_type} '{query_name}':")
    for idx, m in enumerate(matches):
        source = m.get("type", "processed").upper()
        if item_type == "actor":
            birth = f", born {m['birth_year']}" if m.get("birth_year") else ""
            print(f"  [{idx + 1}] {m['name']}{birth} [{m['id']}] (Source: {source})")
        else:
            year = f" ({m['year']})" if m.get("year") else ""
            info = f" - type: {m['title_type']}" if m.get("title_type") else ""
            print(f"  [{idx + 1}] {m['title']}{year}{info} [{m['id']}] (Source: {source})")
    
    while True:
        try:
            choice = input(f"\nSelect a choice (1-{len(matches)}) or Enter to skip: ").strip()
            if not choice:
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                return matches[idx]
        except ValueError:
            pass
        print("Invalid choice. Try again.")


def main():
    parser = argparse.ArgumentParser(description="Connactor cast diagnostic tool")
    parser.add_argument("--actor", help="Actor name or nconst ID")
    parser.add_argument("--movie", help="Movie title or tconst ID")
    args = parser.parse_args()

    actor_query = args.actor
    movie_query = args.movie

    if not actor_query:
        actor_query = input("Enter actor name (e.g. Leonardo DiCaprio) or nconst: ").strip()
    if not movie_query:
        movie_query = input("Enter movie title (e.g. Inception) or tconst: ").strip()

    if not actor_query or not movie_query:
        print("Both actor and movie queries are required to run diagnostics.")
        return

    print("\n" + "=" * 60)
    print("=== Connactor Cast Diagnostic Tool ===")
    print("=" * 60)

    # 1. Load Processed Data
    G, actor_index, movie_index = load_processed_data()

    # 2. Search Actor
    actor_matches = []
    # Search processed graph nodes
    if G:
        for node_id, data in G.nodes(data=True):
            if data.get("type") == "actor":
                if actor_query.lower() in data.get("name", "").lower() or actor_query == node_id:
                    actor_matches.append({
                        "id": node_id,
                        "name": data.get("name"),
                        "birth_year": data.get("birth_year"),
                        "type": "processed"
                    })
    
    # If not found or raw search requested, search raw
    if not actor_matches or actor_query.startswith("nm"):
        raw_actor_matches = find_actor_in_raw(actor_query)
        # merge without duplicating IDs
        seen_ids = {a["id"] for a in actor_matches}
        for rm in raw_actor_matches:
            if rm["id"] not in seen_ids:
                actor_matches.append(rm)

    selected_actor = select_item(actor_matches, actor_query, "actor")
    if not selected_actor:
        print(f"\n❌ ERROR: Could not find actor matching '{actor_query}' in processed or raw databases.")
        return

    # 3. Search Movie
    movie_matches = []
    # Search processed graph nodes
    if G:
        for node_id, data in G.nodes(data=True):
            if data.get("type") == "movie":
                if movie_query.lower() in data.get("title", "").lower() or movie_query == node_id:
                    movie_matches.append({
                        "id": node_id,
                        "title": data.get("title"),
                        "year": data.get("year"),
                        "type": "processed"
                    })
    
    # If not found or raw search requested, search raw
    if not movie_matches or movie_query.startswith("tt"):
        raw_movie_matches = find_movie_in_raw(movie_query)
        # merge without duplicating IDs
        seen_ids = {m["id"] for m in movie_matches}
        for rm in raw_movie_matches:
            if rm["id"] not in seen_ids:
                movie_matches.append(rm)

    selected_movie = select_item(movie_matches, movie_query, "movie")
    if not selected_movie:
        print(f"\n❌ ERROR: Could not find movie matching '{movie_query}' in processed or raw databases.")
        return

    # Diagnostics Run
    nconst = selected_actor["id"]
    tconst = selected_movie["id"]
    actor_name = selected_actor.get("name") or selected_actor.get("label")
    movie_title = selected_movie.get("title") or selected_movie.get("label")

    print("\n" + "-" * 50)
    print(f"DIAGNOSING: '{actor_name}' [{nconst}] ↔ '{movie_title}' [{tconst}]")
    print("-" * 50)

    # 4. Check Processed Graph Presence
    in_graph = False
    actor_in_graph = G is not None and nconst in G
    movie_in_graph = G is not None and tconst in G
    connected_in_graph = False

    if G:
        if actor_in_graph and movie_in_graph:
            connected_in_graph = G.has_edge(nconst, tconst)

    if connected_in_graph:
        print(f"🟢 SUCCESS: The actor and movie are fully connected in the processed graph!")
        print(f"  - Actor popularity rating: {G.nodes[nconst].get('popularity', 0.0)}")
        print(f"  - Movie year: {G.nodes[tconst].get('year')}")
        return

    # If they are not connected, run detailed diagnostics
    print("🔴 CONNECTION NOT FOUND in processed graph. Diagnosing why...")

    # Diagnostic Step A: Check if the movie node is in the graph
    print(f"\n[A] Check Movie Node '{movie_title}' [{tconst}]:")
    if movie_in_graph:
        print("  - Node is present in graph.pkl (Success)")
    else:
        print("  - Node is MISSING from graph.pkl")
        raw_info = get_movie_raw_info(tconst)
        if raw_info:
            print("  - Checked raw title.basics.tsv.gz: Found movie in raw data!")
            title_type = raw_info["title_type"]
            print(f"    - Title Type: '{title_type}'")
            if title_type != "movie":
                print(f"    💡 ROOT CAUSE: Movie was EXCLUDED because its type is '{title_type}'.")
                print("      Our ingestion only parses titles of type 'movie' to avoid bloating the game.")
                return
            else:
                print("    - Movie type is 'movie' (qualifying). It must have been excluded due to other factors.")
        else:
            print("    💡 ROOT CAUSE: Movie is completely missing from raw title.basics.tsv.gz dataset.")
            return

    # Diagnostic Step B: Check if the actor node is in the graph
    print(f"\n[B] Check Actor Node '{actor_name}' [{nconst}]:")
    if actor_in_graph:
        print("  - Node is present in graph.pkl (Success)")
    else:
        print("  - Node is MISSING from graph.pkl")
        raw_info = get_actor_raw_info(nconst)
        if raw_info:
            print("  - Checked raw name.basics.tsv.gz: Found actor in raw data!")
            print(f"    - Listed professions: '{raw_info['professions']}'")
            
            # Count the actor's raw qualifying credits
            raw_credits = scan_raw_principals_for_actor(nconst)
            
            # Load title basics for quick verification (need to verify how many are 'movie' and valid)
            print("    - Evaluating credit types:")
            movie_credits_count = 0
            actor_role_credits_count = 0
            
            for cred in raw_credits:
                role = cred["category"]
                # Only counts as actor/actress roles in movies
                if role in VALID_CATEGORIES:
                    actor_role_credits_count += 1
            
            print(f"      - Total raw credits found: {len(raw_credits)}")
            print(f"      - Credits with actor/actress category: {actor_role_credits_count}")
            
            if actor_role_credits_count < MIN_CREDITS:
                print(f"    💡 ROOT CAUSE: Actor was EXCLUDED because they have only {actor_role_credits_count} qualifying actor credits.")
                print(f"      We require at least {MIN_CREDITS} actor/actress credits in movies. This actor is too obscure for the ingestion.")
                return
            else:
                print(f"      - Actor has {actor_role_credits_count} qualifying credits (>= {MIN_CREDITS}). Missing for another reason.")
        else:
            print("    💡 ROOT CAUSE: Actor is completely missing from raw name.basics.tsv.gz dataset.")
            return

    # Diagnostic Step C: Check the relationship in raw dataset
    print(f"\n[C] Check Relationship in principals list:")
    raw_rel = check_relationship_in_raw_principals(tconst, nconst)
    if raw_rel:
        category = raw_rel["category"]
        print(f"  - Link exists in raw title.principals.tsv.gz with category: '{category}'")
        if category not in VALID_CATEGORIES:
            print(f"  💡 ROOT CAUSE: Connection was EXCLUDED because the actor's role category is '{category}'.")
            print("    We only ingest cast links categorized as 'actor' or 'actress'.")
            print("    Links such as 'self', 'writer', 'director', or 'producer' are skipped by design.")
        else:
            print("  - Category is qualifying. The actor or movie might have been removed during filtering.")
    else:
        print("  💡 ROOT CAUSE: Connection is completely missing from raw title.principals.tsv.gz database.")
        print("    IMDB itself does not list this actor in the cast of this movie!")


if __name__ == "__main__":
    main()
