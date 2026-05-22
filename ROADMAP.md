# Connactor — Roadmap

## Phase 0 — TMDB Data Validation
**Goal:** Verify TMDB has the cast coverage we need before committing to it as our data source.

- [x] Get TMDB API key (free at themoviedb.org/settings/api)
- [x] Write a validation script that samples ~50 well-known movies and checks cast count per film
- [x] Cross-reference a handful of movies against current IMDB-principals graph to compare edge counts
- [x] Verify TMDB daily movie ID export is accessible and parseable
- [x] Confirm `/movie/changes` endpoint gives usable delta for incremental refresh
- [x] Decision: proceed with TMDB or find a hybrid approach

## Phase 1 — Graph DB Foundation
**Goal:** Replace in-memory NetworkX graph with persistent Neo4j backed by TMDB data.

- [x] Add Neo4j to Docker Compose (local dev)
- [x] Write TMDB movie ID export downloader
- [x] Write async TMDB credits crawler (`/movie/{id}/credits`)
- [x] Write async TMDB person enricher (`/person/{id}`) — issue #5
- [x] Write Neo4j bulk data loader (initial full load) — issue #6
- [x] One-command bootstrap pipeline (`bootstrap.py`) with GCS artifact storage
- [ ] Write daily delta refresh job (`/movie/changes`)
- [ ] Write hourly pair pool generator (pre-vetted pairs → Redis) — issue #8

## Phase 2 — API Overhaul
**Goal:** All FastAPI endpoints backed by Neo4j. No NetworkX, no Trie, no pickle.

- [x] Replace `GraphStore` with Neo4j async driver
- [x] Replace Python BFS with Cypher `shortestPath` / `allShortestPaths`
- [x] Replace Trie autocomplete with Neo4j full-text indexes
- [ ] Update `/game` to pop from Redis pair pool
- [ ] Update all remaining endpoints to use Neo4j
- [ ] All 25 existing tests passing against Neo4j

## Phase 3 — Production Infrastructure
**Goal:** API on Cloud Run, database server on Compute Engine, secrets in Secret Manager, automated deploys.

- [ ] Enable GCP APIs (Cloud Run, Artifact Registry, Secret Manager, Compute Engine)
- [ ] Compute Engine VM (e2-highmem-2) + 100 GB persistent disk + daily snapshot schedule
- [ ] Docker Compose on VM for Neo4j + Redis (database server only)
- [ ] VPC networking: Cloud Run Direct VPC Egress → VM (Neo4j :7687, Redis :6379 internal only)
- [ ] GCP Secret Manager: create secrets, bind to Cloud Run service account via IAM
- [ ] Containerise FastAPI (Dockerfile) + push to Artifact Registry
- [ ] Cloud Run service: secrets mounted as env vars, VPC egress enabled
- [ ] GitHub Actions CI/CD: test → build → push to Artifact Registry → deploy to Cloud Run
- [ ] Cloudflare Pages for frontend + custom domain DNS

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
