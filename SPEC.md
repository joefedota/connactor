# Connactor — Product Spec

A word-chain game for movies. Connect two actors through shared films in as few steps as possible.

---

## Overview

Connactor generates a pair of actors and challenges players to build a chain connecting them — each link must be a real movie both actors appeared in. The shorter the chain, the better. After submitting or giving up, the app reveals the optimal path(s) using BFS over IMDB graph data.

---

## V1 — Single Player (current)

### Core gameplay loop

1. **Prompt generation** — app picks two actors at random from the top-500 eligible pool and runs BFS live at request time. Retries until a pair with a 2–6 hop path is found (typically 1–2 attempts). No pre-generation step.

2. **Path building** — player types a movie or actor name. As they type, autocomplete suggestions appear from the full database (spelling assist only — the player must know the connections themselves). Each step: actor → movie → actor → movie → actor.

3. **Validation** — each actor step is validated immediately via `/connected`. If the actor wasn't in the preceding movie, they are not added to the path and an inline error appears (e.g. "Tom Hanks wasn't in Inception — pick someone who was."). Movie steps are unconstrained — any movie can be named. Final path validity is checked against the graph when the game ends.

4. **Finish / give up** — player completes the chain when the target actor is reached. "Give Up" skips straight to the solution.

5. **Results screen** — shows player's path (hop count), all optimal path(s) at minimum hop count (up to 10), and a share button.

### Screens

| Screen | Description |
|--------|-------------|
| Home | Start game button, How to Play modal |
| Game board | Source/target actors locked at top. Autocomplete search alternates between movie and actor mode by position. Inline error on bad connections. |
| Results | Player's path vs optimal path(s), hop count, share button, Play Again |
| How to Play | Modal with Matt Damon → Interstellar → Timothée Chalamet worked example |

---

## Data

### Source
TMDB API (themoviedb.org) — free API key, full cast lists per film, daily exports, incremental change feed.

| Endpoint / File | Used for |
|-----------------|----------|
| `files.tmdb.org/p/exports/movie_ids_*.json.gz` | Full list of movie IDs (daily export, no auth required) |
| `GET /movie/{id}/credits` | Full cast per movie (all credited actors, not just principals) |
| `GET /person/{id}` | Actor name, popularity score, profile image path |
| `GET /movie/changes` | Delta of movies changed in last 24h (for incremental refresh) |

**Why TMDB over IMDB:** IMDB's free bulk TSV exports only include *principal* cast (~10–15 top-billed per film). TMDB's credits endpoint returns all cast in their database — typically 50–200+ for popular films. More edges = more valid paths = better gameplay. See decision log entries #7 and #13.

### Graph filters (applied at ingest time)
- Movies with `vote_count > 50` and `popularity > 1.0` only (~150–200k qualifying films)
- Cast members with `known_for_department = Acting` only
- Actors with ≥ 5 qualifying movie credits

### Starting actor pool filter (applied at pair generation time)
- Starting actors are the top N actors ranked by **TMDB popularity score**
- Pool size varies by difficulty tier (see Difficulty Tiers below)
- This applies only to puzzle start/end actors — the full graph is used during gameplay

---

## Graph & Algorithm

Bipartite graph: actor nodes + movie nodes, edges = actor appeared in movie.

- Shortest path = BFS from source actor to target actor, alternating actor → movie → actor
- All optimal paths: BFS backward from target (builds distance map), then DFS from source constrained to optimal edges only, capped at 10 paths
- Pair generation: live BFS at `/game` request time, retries until 2–6 hop path found, sampled from eligible actor pool
- Shortest path and all-paths queries run via Cypher (`shortestPath` / `allShortestPaths`) against Neo4j
- Pair generation: Cypher random sample from rank-bounded actor pool + shortestPath filter, retries until valid pair found
- Autocomplete: Neo4j full-text indexes (`actorNames`, `movieTitles`)

---

## Tech Stack

| Layer | v1 (shipped) | Current (Phase 2) | Production (target) |
|-------|-------------|-------------------|-------------------|
| Frontend | React 18 + TypeScript, Vite, Zustand, React Router | Unchanged | Deployed to Cloudflare Pages |
| Backend | Python + FastAPI, NetworkX bipartite graph in memory | FastAPI + Neo4j async driver (stateless, ~1s startup) | Unchanged |
| Graph DB | NetworkX in-memory (~1–2 GB RAM, single process) | Neo4j Community Edition (local Docker) | Neo4j on GCP Compute Engine |
| Data source | IMDB bulk TSV dumps (principals only, ~10–15 cast/film) | TMDB API (full cast, ~50–200/film) | Unchanged |
| Autocomplete | In-memory Trie (custom implementation) | Neo4j full-text indexes (Lucene-backed) | Unchanged |
| Caching | None | None (Redis pair pool in Phase 3) | Redis (pair pool + solve results) |
| Hosting | Local only | Local only | GCP Compute Engine + Cloudflare Pages |
| Auth | None (v1) | None (v1) | None (v1) — JWT in v2 |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/game` | Live BFS to find a valid random actor pair (2–6 hops) |
| POST | `/validate` | Validate full path — called when game ends |
| POST | `/solve` | All optimal paths — called on give up or game completion |
| GET | `/autocomplete?q=...&type=actor\|movie` | Unconstrained prefix search |
| GET | `/connected?a=...&b=...` | Check whether two nodes share an edge — used for per-step actor validation |
| GET | `/health` | Graph stats |

---

## V1.5 — Franchise Blocklist (future)

Maintain `excluded_titles.json` keyed by IMDB tconst. Filter at graph-build time so excluded films are invisible to autocomplete, validation, and BFS.

Candidates for exclusion:
- MCU (Iron Man 2008 onward) — large ensemble, trivializes graph
- Sony SPUMC (Venom 2018+, Morbius, Madame Web, Kraven)
- X-Men / Fox Marvel (2000–2019)
- Fast & Furious franchise

Candidates to keep:
- Sony Spider-Man Raimi + Webb trilogies (pre-MCU, no ensemble shortcut problem)
- DCU / DCEU

---

## V2 — Multiplayer (future)

- Room codes (4-character), no accounts needed
- All players see the same actor pair simultaneously
- Live sidebar shows who has submitted (not their answer)
- Leaderboard ranked by fewest hops, then fastest time
- Bonus star for matching optimal path
- WebSockets via Socket.io, room state in Redis
- Auth required for scoring persistence (email or Google SSO)

---

## V3 — Daily Challenge (future)

- Curated pair of the day, Wordle-style
- Shared result with date stamp
- Requires CMS or scheduled job

---

## Decision Log

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Movies only, no TV | Keeps the graph focused and connections more recognizable |
| 2 | Actor → movie → actor explicit chain (not actors-only) | More interesting gameplay — player must know the connecting film, not just the actors |
| 3 | Autocomplete is unconstrained (full DB, not neighbor-filtered) | Constrained search made the game too easy — showed valid answers. Player must know the connection; autocomplete only helps with spelling |
| 4 | Validate actor steps immediately via `/connected`; movies are unconstrained | Gives instant feedback when an actor wasn't in the preceding movie, without blocking free movie exploration. Movie validation would remove creative routing. |
| 5 | Live BFS at `/game` time, no pre-generated pairs | Pre-generation limits variety to a fixed pool and adds an offline script dependency. BFS on the in-memory graph is fast (< 100 ms); retrying a few random pairs until a 2–6 hop pair is found is trivially cheap. |
| 6 | Starting actors = top 500 by aggregate IMDB vote count across filmography (movies only, TV excluded) | Better signal of sustained popularity than a single-movie threshold. Iterated: tried per-movie thresholds (5k, 20k votes), settled on top-500 aggregate ranking. TV ratings excluded because the graph only contains movie nodes. Full graph is unfiltered so gameplay is unrestricted. |
| 7 | IMDB vote count as box office proxy (v1) | At v1 build time TMDB API access was assumed to require a business account. IMDB's `title.ratings.tsv.gz` is free and bulk. This decision is superseded by #13. |
| 8 | NetworkX bipartite graph in memory, no database | Simple and fast for v1. ~1–2 GB RAM for the full graph. Swap to a graph DB only if multi-server or memory becomes a constraint. Superseded by #14. |
| 9 | Blocklist deferred to v1.5 | Not critical for core gameplay; adds complexity to ingest. Human-editable JSON so it can be added without a code deploy when ready. |
| 10 | No difficulty tiers in v1 | Adds UI and pair-generation complexity without clear player benefit at launch. Can add later once hop distribution is understood. |
| 11 | No auth in v1 | Reduces friction to zero. Multiplayer (v2) is where auth becomes necessary for scoring persistence. |
| 12 | Autocomplete shows release year for movies | Disambiguates remakes and multiple versions of the same title in the dropdown (e.g. two "La La Land" entries). Year stored on movie nodes at ingest and surfaced in all NodeInfo responses. |
| 13 | Switch data source from IMDB to TMDB | IMDB free TSV dumps only include principal cast (~10–15 per film). TMDB's `/movie/{id}/credits` returns all credited cast (50–200+ for popular films), giving the graph significantly more edges and gameplay paths. TMDB offers a free API key and a daily movie ID export file.<br><br>**Validation Findings (Phase 0 - May 2026):**<br>- **Cast Coverage**: Verification script `validate_tmdb.py` demonstrated a **300% to 1200% edge count increase** over the current IMDB-principals graph. Popular films expanded from 10 principals to 50–150+ actors (including niche voice actors and cameos like Paul Bettany in *Iron Man*).<br>- **Daily Exports**: Confirmed daily unauthenticated NDJSON gzipped export downloads from `files.tmdb.org` work flawlessly, yielding ~1.2M rows that filter down to ~35,486 high-quality films when popularity > 1.0.<br>- **Changes Endpoint**: Confirmed `/movie/changes` returns ~1,000–5,000 daily modified IDs, proving the feasibility of lightweight incremental updates. |
| 14 | Switch from NetworkX in-memory to Neo4j graph DB | Removes 1–2 GB RAM requirement, eliminates 15–30s cold start, enables horizontal scaling, and gives native Cypher `shortestPath` / `allShortestPaths` instead of custom BFS. Neo4j Community Edition is free; self-hosted on GCP at ~$75/mo vs $650–975/mo for managed AuraDB. |
| 15 | Self-hosted Neo4j on GCP VM, not AuraDB managed | AuraDB Professional costs ~$65/GB/month. The production dataset (~10–15 GB) would cost $650–975/mo. Self-hosting on a GCP e2-highmem-2 VM with a persistent disk costs ~$75/mo total. Data safety achieved via GCP snapshot schedule (daily, 7-day retention) rather than managed backup. |
