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

- [x] Enable GCP APIs (Cloud Run, Artifact Registry, Secret Manager, Compute Engine)
- [x] Compute Engine VM (e2-highmem-2) + 100 GB persistent disk + daily snapshot schedule
- [x] Docker Compose on VM for Neo4j (Redis deferred — backlogged with #8 pair pool)
- [x] VPC networking: Cloud Run Direct VPC Egress → VM (Neo4j :7687 internal only)
- [x] GCP Secret Manager: create secrets, bind to Cloud Run service account via IAM
- [x] Containerise FastAPI (Dockerfile) + push to Artifact Registry
- [x] Cloud Run service: secrets mounted as env vars, VPC egress enabled
- [x] Cloud Run Jobs + Cloud Scheduler: nightly full re-crawl
- [x] GitHub Actions CI/CD: test → build → push to Artifact Registry → deploy to Cloud Run (#12)
- [x] Cloudflare Pages for frontend + custom domain DNS (connactor.com / api.connactor.com) (#13)

## Phase 4 — Images + Polish
**Goal:** Actor headshots and movie posters in the UI.

- [x] Surface `profile_path` / `poster_path` in API responses (#37)
- [x] Add actor thumbnail to `NodeChip` component (#37)
- [x] Add movie poster to `NodeChip` component (#37)
- [x] Handle missing images gracefully (#37)

## Phase 4.5 — Content Filtering
**Goal:** Prevent low-quality or irrelevant entries from appearing in optimal paths.

- [x] Exclude movies with `vote_count < 100` from optimal paths (#solve query)
- [x] Exclude documentaries (TMDB genre ID 99) from optimal paths
- [x] Store `genre_ids` on Movie nodes via pipeline crawl
- [ ] Re-run pipeline to populate `genre_ids` on existing nodes
- [ ] Marvel kill switch (#52)

## Phase 5 — Franchise Blocklist (v1.5)
**Goal:** Filter large ensemble franchises that trivialize the graph.

- [ ] Implement `excluded_titles.json` filtering at ingest time
- [ ] Define initial blocklist (MCU, X-Men, Fast & Furious, Sony SPUMC)
- [ ] Test graph connectivity after filtering

## Phase 6 — Multiplayer (v2)
**Goal:** Real-time multiplayer rooms.

- [ ] JWT auth (email or Google SSO)
- [x] Postgres for user state — Neon (free tier), schema covers users + puzzles + completions — issue #44
- [ ] WebSocket room system (Redis pub/sub)
- [ ] Leaderboard ranked by hops + time
- [ ] Bonus star for optimal path

## Phase 7 — Daily Challenge (v3)
**Goal:** Wordle-style shared daily puzzle.

- [x] Generalized puzzle persistence — every played pair becomes a persisted puzzle with UUID — issue #44
- [x] Anonymous user identity — itsdangerous-signed HTTPOnly cookie — issue #44
- [x] Game completion tracking — all game completions recorded against puzzle + user — issue #44
- [x] Pre-generate curated daily pair — `bin/generate_daily_puzzle.py` Cloud Run Job — issue #44
- [x] `GET /daily` endpoint returning today's pair + user completion status + streak — issue #44
- [x] `POST /complete` unified completion endpoint (daily + random) — issue #44
- [x] Share result with date stamp — issue #44
- [x] Daily Challenge button on home screen + `/daily` route — issue #44
- [ ] Historical results page
- [ ] Streak display in UI (streak computed server-side, display deferred)
- [ ] Emoji grid share format (v1.5)

## Phase 8 — Ops & Observability
**Goal:** Don't get surprised by spend or by traffic going to zero.

- [x] Daily cost + usage email (GCP BigQuery billing export + Cloudflare Web Analytics + Resend) — issue #47
