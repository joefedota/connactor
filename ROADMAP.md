# Connactor — Roadmap

## Phase 0 — TMDB Data Validation
**Goal:** Verify TMDB has the cast coverage we need before committing to it as our data source.

- [ ] Get TMDB API key (free at themoviedb.org/settings/api)
- [ ] Write a validation script that samples ~50 well-known movies and checks cast count per film
- [ ] Cross-reference a handful of movies against current IMDB-principals graph to compare edge counts
- [ ] Verify TMDB daily movie ID export is accessible and parseable
- [ ] Confirm `/movie/changes` endpoint gives usable delta for incremental refresh
- [ ] Decision: proceed with TMDB or find a hybrid approach

## Phase 1 — Graph DB Foundation
**Goal:** Replace in-memory NetworkX graph with persistent Neo4j backed by TMDB data.

- [ ] Add Neo4j to Docker Compose (local dev)
- [ ] Write TMDB movie ID export downloader
- [ ] Write async TMDB credits crawler (`/movie/{id}/credits`)
- [ ] Write async TMDB person enricher (`/person/{id}`)
- [ ] Write Neo4j bulk data loader (initial full load)
- [ ] Write daily delta refresh job (`/movie/changes`)
- [ ] Write hourly pair pool generator (pre-vetted pairs → Redis)

## Phase 2 — API Overhaul
**Goal:** All FastAPI endpoints backed by Neo4j. No NetworkX, no Trie, no pickle.

- [ ] Replace `GraphStore` with Neo4j async driver
- [ ] Replace Python BFS with Cypher `shortestPath` / `allShortestPaths`
- [ ] Replace Trie autocomplete with Neo4j full-text indexes
- [ ] Update `/game` to pop from Redis pair pool
- [ ] Update all remaining endpoints to use Neo4j
- [ ] All 25 existing tests passing against Neo4j

## Phase 3 — Production Infrastructure
**Goal:** Running on GCP, automated deploys, data stays safe.

- [ ] GCP Compute Engine VM (e2-highmem-2) + 100 GB persistent disk
- [ ] GCP snapshot schedule (daily backups)
- [ ] Docker Compose production config (Nginx + TLS via Let's Encrypt)
- [ ] GitHub Actions CI/CD (test → build → deploy)
- [ ] Cloudflare Pages for frontend
- [ ] Environment secrets management

## Phase 4 — Images + Polish
**Goal:** Actor headshots and movie posters in the UI.

- [ ] Surface `profile_path` / `poster_path` in API responses
- [ ] Add actor thumbnail to `NodeChip` component
- [ ] Add movie poster to `NodeChip` component
- [ ] Handle missing images gracefully

## Phase 5 — Franchise Blocklist (v1.5)
**Goal:** Filter large ensemble franchises that trivialize the graph.

- [ ] Implement `excluded_titles.json` filtering at ingest time
- [ ] Define initial blocklist (MCU, X-Men, Fast & Furious, Sony SPUMC)
- [ ] Test graph connectivity after filtering

## Phase 6 — Multiplayer (v2)
**Goal:** Real-time multiplayer rooms.

- [ ] JWT auth (email or Google SSO)
- [ ] Postgres for user accounts and leaderboards
- [ ] WebSocket room system (Redis pub/sub)
- [ ] Leaderboard ranked by hops + time
- [ ] Bonus star for optimal path

## Phase 7 — Daily Challenge (v3)
**Goal:** Wordle-style shared daily puzzle.

- [ ] Pre-generate curated daily pair (scheduled job)
- [ ] `/daily` endpoint returning today's pair
- [ ] Share result with date stamp
- [ ] Historical results page
