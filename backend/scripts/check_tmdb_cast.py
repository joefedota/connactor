#!/usr/bin/env python3
"""
Targeted TMDb Cast Checker (Diagnostic Script)

Allows querying a movie (e.g. "Iron Man") and searching for a specific actor (e.g. "Paul Bettany")
directly on TMDb to check if they are in the cast list, showing character name and billing order.
"""
from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DOTENV_PATH = BACKEND_DIR / ".env"

def load_env() -> dict[str, str]:
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

def get_credentials() -> tuple[str | None, str | None]:
    env = load_env()
    api_key = os.getenv("TMDB_API_KEY") or env.get("TMDB_API_KEY")
    bearer_token = os.getenv("TMDB_API_READ_TOKEN") or env.get("TMDB_API_READ_TOKEN")
    return api_key, bearer_token

def make_request(url: str, api_key: str | None, bearer_token: str | None) -> dict:
    req = urllib.request.Request(url)
    req.add_header("accept", "application/json")
    if bearer_token:
        req.add_header("Authorization", f"Bearer {bearer_token}")
    else:
        separator = "&" if "?" in url else "?"
        req.full_url = f"{url}{separator}api_key={api_key}"
        
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason} for URL: {url}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise

def main() -> None:
    print("=== Connactor TMDb Cast Verification ===")
    
    api_key, bearer_token = get_credentials()
    if not api_key and not bearer_token:
        print("\n[WARNING] TMDb API credentials not found.")
        print(f"Please create a `.env` file in the backend directory or set the environment variables:")
        print("  TMDB_API_KEY=your_api_key")
        print("  or")
        print("  TMDB_API_READ_TOKEN=your_bearer_token")
        print("\nYou can get a free key by registering at https://www.themoviedb.org/settings/api")
        print("\nEnter your TMDb API Key or Bearer Token now to run the verification:")
        user_input = input("Credential: ").strip()
        if not user_input:
            print("No credential provided. Exiting.")
            sys.exit(1)
        if len(user_input) > 100:
            bearer_token = user_input
            with open(DOTENV_PATH, "a", encoding="utf-8") as f:
                f.write(f"\nTMDB_API_READ_TOKEN={bearer_token}\n")
        else:
            api_key = user_input
            with open(DOTENV_PATH, "a", encoding="utf-8") as f:
                f.write(f"\nTMDB_API_KEY={api_key}\n")
        print("Saved credentials to .env.")

    # Get inputs
    movie_query = input("\nEnter Movie Title to search (e.g. Iron Man): ").strip()
    if not movie_query:
        movie_query = "Iron Man"
    actor_query = input("Enter Actor Name to search for (e.g. Paul Bettany): ").strip()
    if not actor_query:
        actor_query = "Paul Bettany"

    print(f"\n[1/3] Searching TMDb for movie: '{movie_query}' ...")
    encoded_query = urllib.parse.quote(movie_query)
    search_url = f"https://api.themoviedb.org/3/search/movie?query={encoded_query}"
    
    try:
        search_res = make_request(search_url, api_key, bearer_token)
        results = search_res.get("results", [])
        if not results:
            print(f"No movies found matching '{movie_query}' on TMDb.")
            return
            
        # Display top 3 results and pick the first one
        print("Top matches found:")
        for idx, item in enumerate(results[:3], 1):
            print(f"  {idx}. {item['title']} ({item.get('release_date', 'N/A')[:4]}) - TMDb ID: {item['id']}")
            
        selected_movie = results[0]
        movie_id = selected_movie["id"]
        movie_title = selected_movie["title"]
        movie_year = selected_movie.get("release_date", "N/A")[:4]
        
        print(f"\n[2/3] Fetching complete credit details for: {movie_title} ({movie_year}) ...")
        credits_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"
        credits_res = make_request(credits_url, api_key, bearer_token)
        
        cast = credits_res.get("cast", [])
        crew = credits_res.get("crew", [])
        total_credits = len(cast) + len(crew)
        
        print(f"\n📈 TMDb Credit Metrics for '{movie_title}':")
        print(f"  • Total Cast Members: {len(cast):,}")
        print(f"  • Total Crew Members: {len(crew):,}")
        print(f"  • Total Credits:      {total_credits:,}")
        
        # Option to dump entire cast list
        print(f"\nWould you like to print all {len(cast)} cast members? (y/N): ", end="")
        dump_choice = input().strip().lower()
        if dump_choice in ("y", "yes"):
            print(f"\n=== Full Cast List for {movie_title} ({len(cast)} entries) ===")
            print(f"{'Order':<6} | {'Actor Name':<30} | {'Character Role':<45}")
            print("-" * 90)
            for m in cast:
                role = m.get("character", "Unknown")
                print(f"{m.get('order', 0):<6} | {m['name']:<30} | {role:<45}")
            print("=" * 90)
            
        print(f"\n[3/3] Searching cast list for '{actor_query}' ...")
        matches = []
        for member in cast:
            if actor_query.lower() in member["name"].lower():
                matches.append(member)
                
        if not matches:
            print(f"❌ '{actor_query}' was NOT found in the TMDb cast list of '{movie_title}'.")
            # Print top 15 cast members to show who is there
            print("\nTop 15 billed cast members on TMDb:")
            for member in cast[:15]:
                print(f"  - {member['name']} as '{member['character']}' (Billing order: {member['order']})")
        else:
            print(f"✅ SUCCESS! Found match(es) for '{actor_query}':")
            for m in matches:
                print(f"\n  • Actor Name:      {m['name']}")
                print(f"    Character Role:  {m['character']}")
                print(f"    Billing Order:   {m['order']} (index in cast array)")
                print(f"    TMDb Person ID:  {m['id']}")
                print(f"    Profile Image:   https://image.tmdb.org/t/p/w185{m.get('profile_path')}" if m.get('profile_path') else "    Profile Image:   No image")
                
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
