#!/usr/bin/env python3
"""
TMDb Data Validation Script (Phase 0)

Verifies the data quality and coverage of TMDb before migrating.
Tasks performed:
1. Samples ~50 well-known movies from the local graph.
2. Resolves each movie's IMDB tconst to TMDb ID using the /find endpoint.
3. Fetches TMDb cast lists and compares counts against the current IMDB principals graph.
4. Verifies accessibility of TMDb daily movie ID exports.
5. Tests the TMDb `/movie/changes` endpoint for delta refreshes.
"""
from __future__ import annotations

import datetime
import gzip
import json
import os
import pickle
import sys
import urllib.request
import urllib.error
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"
DOTENV_PATH = BACKEND_DIR / ".env"

def load_env() -> dict[str, str]:
    """Load env vars from .env file manually to avoid dependency overhead."""
    env = {}
    if DOTENV_PATH.exists():
        with open(DOTENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("=", 1)
                if len(parts) == 2:
                    env[parts[0].strip()] = parts[1].strip().strip('"').strip("'")
    return env

def get_api_credentials() -> tuple[str | None, str | None]:
    """Retrieve API key or Bearer Token from environment or .env."""
    env = load_env()
    
    # Check OS env first, then .env file
    api_key = os.getenv("TMDB_API_KEY") or env.get("TMDB_API_KEY")
    bearer_token = os.getenv("TMDB_API_READ_TOKEN") or env.get("TMDB_API_READ_TOKEN")
    
    return api_key, bearer_token

def make_tmdb_request(url: str, api_key: str | None, bearer_token: str | None) -> dict:
    """Execute a request to the TMDb API, handling query params or Bearer token auth."""
    if bearer_token:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {bearer_token}")
        req.add_header("accept", "application/json")
    else:
        # Append api_key query parameter
        separator = "&" if "?" in url else "?"
        url_with_key = f"{url}{separator}api_key={api_key}"
        req = urllib.request.Request(url_with_key)
        req.add_header("accept", "application/json")
        
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason} for URL: {url}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"Error during TMDb request: {e}", file=sys.stderr)
        raise

def sample_popular_movies(count: int = 50) -> list[dict]:
    """Load movie_index.json and select the top `count` movies by votes."""
    movie_index_path = PROCESSED_DIR / "movie_index.json"
    if not movie_index_path.exists():
        print(f"Error: movie_index.json not found at {movie_index_path}. Build the graph first.")
        sys.exit(1)
        
    with open(movie_index_path, "r", encoding="utf-8") as f:
        movies = json.load(f)
        
    # Sort descending by votes
    movies.sort(key=lambda x: x.get("votes", 0), reverse=True)
    return movies[:count]

def main() -> None:
    print("=== Connactor TMDb Validation (Phase 0) ===")
    
    api_key, bearer_token = get_api_credentials()
    
    if not api_key and not bearer_token:
        print("\n[WARNING] TMDb API credentials not found.")
        print(f"Please create a `.env` file at {DOTENV_PATH} or set the environment variables:")
        print("  TMDB_API_KEY=your_api_key")
        print("  or")
        print("  TMDB_API_READ_TOKEN=your_bearer_token")
        print("\nYou can get a free key by registering at https://www.themoviedb.org/settings/api")
        print("\nEnter your TMDb API Key or Bearer Token now to run the validation:")
        user_input = input("Credential: ").strip()
        if not user_input:
            print("No credential provided. Exiting.")
            sys.exit(1)
        if len(user_input) > 100:  # Likely a JWT / Bearer Token
            bearer_token = user_input
            # Let's save it to .env for subsequent runs
            with open(DOTENV_PATH, "a", encoding="utf-8") as f:
                f.write(f"\nTMDB_API_READ_TOKEN={bearer_token}\n")
            print(f"Saved Bearer Token to {DOTENV_PATH}")
        else:
            api_key = user_input
            with open(DOTENV_PATH, "a", encoding="utf-8") as f:
                f.write(f"\nTMDB_API_KEY={api_key}\n")
            print(f"Saved API Key to {DOTENV_PATH}")

    # Load local graph for comparison
    graph_path = PROCESSED_DIR / "graph.pkl"
    if not graph_path.exists():
        print(f"Error: graph.pkl not found at {graph_path}. Please run ingestion first.")
        sys.exit(1)
        
    print(f"Loading local bipartite graph to compare edges ...")
    with open(graph_path, "rb") as f:
        G = pickle.load(f)

    # 1. Compare Cast Coverage
    print("\n[1/3] Sampling 50 well-known movies and comparing cast coverage...")
    popular_movies = sample_popular_movies(50)
    
    comparison_table = []
    total_imdb_cast = 0
    total_tmdb_cast = 0
    failures = 0
    
    for idx, movie in enumerate(popular_movies, 1):
        imdb_id = movie["id"]  # e.g., "tt0111161"
        title = movie["label"]
        year = movie.get("year", "N/A")
        
        # Current local graph neighbor count
        if imdb_id in G:
            imdb_cast_count = len(list(G.neighbors(imdb_id)))
        else:
            imdb_cast_count = 0
            
        print(f"  [{idx:2d}/50] Resolving {title} ({year}) [{imdb_id}] ...", end="", flush=True)
        
        try:
            # Step 1: Find movie TMDb ID from IMDB tconst
            find_url = f"https://api.themoviedb.org/3/find/{imdb_id}?external_source=imdb_id"
            find_res = make_tmdb_request(find_url, api_key, bearer_token)
            
            movie_results = find_res.get("movie_results", [])
            if not movie_results:
                print(" -> [NOT FOUND ON TMDB]")
                failures += 1
                continue
                
            tmdb_movie = movie_results[0]
            tmdb_id = tmdb_movie["id"]
            
            # Step 2: Fetch credits
            credits_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits"
            credits_res = make_tmdb_request(credits_url, api_key, bearer_token)
            
            # Filter to actors only (known_for_department == Acting, or just in 'cast' list)
            tmdb_cast = credits_res.get("cast", [])
            # Filter cast if needed, but TMDb's 'cast' list contains actors/actresses only
            tmdb_cast_count = len(tmdb_cast)
            
            increase = tmdb_cast_count - imdb_cast_count
            pct_inc = (increase / imdb_cast_count * 100) if imdb_cast_count > 0 else 0
            
            total_imdb_cast += imdb_cast_count
            total_tmdb_cast += tmdb_cast_count
            
            comparison_table.append({
                "title": f"{title} ({year})",
                "imdb_id": imdb_id,
                "imdb_count": imdb_cast_count,
                "tmdb_count": tmdb_cast_count,
                "increase": increase,
                "pct": pct_inc
            })
            print(f" -> IMDB: {imdb_cast_count} | TMDb: {tmdb_cast_count} (+{increase:d} / +{pct_inc:.1f}%)")
            
        except Exception as e:
            print(f" -> [ERROR: {e}]")
            failures += 1
            
    # Print Markdown Summary Table
    print("\n=== CAST COVERAGE COMPARISON SUMMARY ===")
    print("| Movie Title | IMDB Principals | TMDb Complete Cast | Difference | % Increase |")
    print("|:---|:---:|:---:|:---:|:---:|")
    for row in comparison_table[:20]:  # Show top 20 in terminal to prevent clutter
        print(f"| {row['title']} | {row['imdb_count']} | {row['tmdb_count']} | +{row['increase']} | +{row['pct']:.1f}% |")
    if len(comparison_table) > 20:
        print(f"| ... and {len(comparison_table)-20} more popular movies ... | | | | |")
        
    if total_imdb_cast > 0:
        avg_inc = (total_tmdb_cast - total_imdb_cast) / total_imdb_cast * 100
        print(f"\n👉 TOTAL EDGES OVER SAMPLED FILMS: IMDB: {total_imdb_cast} | TMDb: {total_tmdb_cast} (+{avg_inc:.1f}% average edge increase!)")
    else:
        print(f"\n👉 Total TMDb cast edges resolved: {total_tmdb_cast}")

    # 2. Verify daily ID exports access
    print("\n[2/3] Verifying accessibility of TMDb Daily ID Exports...")
    today = datetime.datetime.utcnow()
    # Check today and yesterday (since files are generated at ~8:00 AM UTC and might lag)
    dates_to_try = [
        today.strftime("%m_%d_%Y"),
        (today - datetime.timedelta(days=1)).strftime("%m_%d_%Y")
    ]
    
    export_verified = False
    for date_str in dates_to_try:
        url = f"https://files.tmdb.org/p/exports/movie_ids_{date_str}.json.gz"
        print(f"  Attempting to check metadata for {url} ...")
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    length = resp.getheader("Content-Length")
                    size_mb = int(length) / (1024 * 1024) if length else 0
                    print(f"  [SUCCESS] Movie export file verified! Date: {date_str} | Size: {size_mb:.2f} MB")
                    export_verified = True
                    break
        except urllib.error.HTTPError as e:
            print(f"  HEAD request returned status {e.code} for date {date_str}")
        except Exception as e:
            print(f"  Connection error: {e}")
            
    if not export_verified:
        print("  [ERROR] Daily movie ID export download check failed. Please verify files.tmdb.org routing.")

    # 3. Test changes endpoint for delta
    print("\n[3/3] Testing TMDb changes endpoint for delta refresh...")
    try:
        yesterday_str = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")
        changes_url = f"https://api.themoviedb.org/3/movie/changes?start_date={yesterday_str}&end_date={today_str}"
        print(f"  Querying movie changes from {yesterday_str} to {today_str} ...")
        changes_res = make_tmdb_request(changes_url, api_key, bearer_token)
        results = changes_res.get("results", [])
        print(f"  [SUCCESS] Changes feed functional! Found {len(results):,} modified movie IDs in 24h.")
    except Exception as e:
        print(f"  [ERROR] Changes endpoint request failed: {e}")

    print("\n=== Validation Completed ===")

if __name__ == "__main__":
    main()
