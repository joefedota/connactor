#!/usr/bin/env python3
"""
Debug tool to check the popularity score of a given actor.
Loads the processed graph and movie index to show exact vote counts and popularity math.

Usage:
    uv run scripts/check_popularity.py "Tom Hanks"
"""
import sys
import pickle
import json
import math
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"


def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Enter actor name to check: ").strip()

    if not query:
        print("Please enter a name to search.")
        return

    graph_path = PROCESSED_DIR / "graph.pkl"
    movie_index_path = PROCESSED_DIR / "movie_index.json"

    if not graph_path.exists() or not movie_index_path.exists():
        print("Processed data files not found. Please run the ingestion first.")
        return

    print("Loading database...")
    with open(graph_path, "rb") as f:
        G = pickle.load(f)

    with open(movie_index_path) as f:
        movie_index = json.load(f)

    # Map movie ID to votes and metadata
    movie_votes = {m["id"]: m.get("votes", 0) for m in movie_index}
    movie_titles = {m["id"]: f"{m['label']} ({m['year']})" if m.get('year') else m['label'] for m in movie_index}

    # Find matching actors
    matches = []
    for node_id, data in G.nodes(data=True):
        if data.get("type") == "actor":
            name = data.get("name", "")
            if query.lower() in name.lower():
                matches.append((node_id, data))

    if not matches:
        print(f"No actors found matching '{query}'.")
        return

    print(f"\nFound {len(matches)} matching actor(s):\n" + "=" * 50)

    for nconst, data in matches[:5]:
        name = data.get("name")
        popularity = data.get("popularity", 0.0)
        birth = data.get("birth_year")
        birth_str = f" (born {birth})" if birth else ""

        print(f"\n👤 ACTOR: {name}{birth_str} [{nconst}]")
        print(f"⭐ Computed Popularity: {popularity} / 10.0")

        # Get and sort movie credits
        credits = []
        for nbr in G.neighbors(nconst):
            if G.nodes[nbr].get("type") == "movie":
                votes = movie_votes.get(nbr, 0)
                title = movie_titles.get(nbr, f"Unknown Movie ({nbr})")
                credits.append((votes, title, nbr))

        credits.sort(reverse=True, key=lambda x: x[0])

        print(f"🎥 Connected Movies ({len(credits)} total), sorted by votes:")
        for idx, (votes, title, tconst) in enumerate(credits[:10]):
            prefix = "👉 [TOP 3] " if idx < 3 else "  - "
            print(f"{prefix}{title:<45} | Votes: {votes:,} [{tconst}]")

        if len(credits) > 10:
            print(f"  ... and {len(credits) - 10} more movies")

        # Show exact math
        top_3 = [votes for votes, _, _ in credits[:3]]
        if not top_3:
            print("\nMath: No movies found.")
            continue

        avg_votes = sum(top_3) / len(top_3)
        calculated_pop = round(math.log10(avg_votes + 1), 2)
        print("\n🧮 Popularity Math Details:")
        print(f"  Top 3 votes: {[f'{v:,}' for v in top_3]}")
        print(f"  Average of top 3: {avg_votes:,.2f}")
        print(f"  log10(average + 1) = log10({avg_votes + 1:,.2f}) = {calculated_pop}")
        print("-" * 50)

    if len(matches) > 5:
        print(f"\n... and {len(matches) - 5} more matches (truncated).")


if __name__ == "__main__":
    main()
