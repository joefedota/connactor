# Connactor — Production System Design

## Overview

This document captures the target production architecture for Connactor. The v1 implementation runs an in-memory NetworkX graph built from IMDB TSV dumps. The production system replaces that with a persistent Neo4j graph built from the TMDB API, hosted on GCP.

---

## Why TMDB, Not IMDB

IMDB's free bulk TSV exports only include **principal cast** (top ~10–15 billed per film). TMDB's `/movie/{id}/credits` endpoint returns **all cast in their database** — for popular films that's 50–200+ actors. More cast entries = more graph edges = more valid paths = better gameplay.

IMDB does not offer a free API for full cast data. Their full credits are available on imdb.com but scraping violates their ToS. TMDB is the right data source.

---

## Architecture

```
TMDB API
  └─► ingest service (async crawler)
        └─► Neo4j (persistent graph DB, GCP VM)
              └─► FastAPI backend
                    ├─► Postgres/Neon (user identity + puzzle + completion state)
                    └─► Redis (pair pool + solve cache, deferred)
                          └─► React frontend (Cloudflare Pages)
```

---

## Data Pipeline

### Initial Full Load (~4–6 hours, run once)

1. Download TMDB daily movie ID export (`files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz`)
2. Filter at the export to `adult=false` and `popularity > 0.1` (~100–200k candidates) — a deliberately loose net since TMDB's `popularity` is a daily-decaying engagement score, not a quality proxy
3. Async crawl `/movie/{id}` and `/movie/{id}/credits` at ~35 req/s for all candidates (`vote_count` only ships on the per-movie endpoint, not in the daily export)
4. Async crawl `/person/{id}` for all unique person IDs
5. Bulk load into Neo4j via Python neo4j driver using `MERGE` in batches. **The Movie node load filters by `vote_count > 100` (with a `popularity > 1.0` grace window for brand-new movies that haven't accumulated votes yet) — see `_should_load_movie` in `load_neo4j.py`.** End state: ~16–18k high-signal Movie nodes. (Why a two-stage filter: the TMDB daily export only exposes `popularity`; vote_count lives on the per-movie crawl. A loose popularity gate at export time + a strict vote_count gate at load time keeps catalog hits like *The Internship* (2013, popularity 0.2, votes 4,471) while excluding the long tail of obscure new releases.)

### Daily Delta Refresh (cron, 9 AM UTC)

1. `GET /movie/changes?start_date={yesterday}&end_date={today}` — returns ~1–5k changed movie IDs
2. Re-crawl `/movie/{id}/credits` for each changed movie
3. MERGE new nodes/edges into Neo4j, remove stale edges

### Hourly Pair Pool Refresh (cron)

Pre-generate 100 valid actor pairs per difficulty tier and store in Redis. Eliminates the 50-retry BFS loop from v1.

---

## Postgres Data Model (User State)

Hosted on **Neon** (serverless Postgres, free tier). Accessed via SQLAlchemy async + asyncpg.

```sql
users(
  user_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)

-- Every unique actor pair played becomes a puzzle row.
-- Daily puzzles are stamped with is_daily=TRUE and scheduled_date.
-- If a randomly-played pair is later chosen as the daily, the same row is reused (UPSERT).
puzzles(
  puzzle_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id      INT  NOT NULL,
  target_id      INT  NOT NULL,
  optimal_hops   INT  NOT NULL,
  is_daily       BOOL NOT NULL DEFAULT FALSE,
  scheduled_date DATE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (source_id, target_id)
)

-- Every completed game, daily or random, is recorded here.
game_completions(
  completion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(user_id),
  puzzle_id     UUID NOT NULL REFERENCES puzzles(puzzle_id),
  hops          INT  NOT NULL,
  time_ms       INT,
  completed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, puzzle_id)
)
```

**Anonymous identity**: HTTPOnly cookie signed with `itsdangerous.URLSafeSerializer`. Created on first request, persists 2 years. No login required.

---

## Graph Data Model

### Nodes

```
(:Actor {
  person_id:    12345,
  name:         "Kevin Bacon",
  popularity:   24.7,
  rank:         42,           // position in sorted popularity list
  profile_path: "/abc.jpg",   // TMDB relative image path
  birth_year:   1958
})

(:Movie {
  movie_id:    1574,
  title:       "Sleepers",
  year:        1996,
  vote_count:  45000,
  popularity:  12.3,
  poster_path: "/xyz.jpg"
})
```

### Edges

```
(:Actor)-[:APPEARED_IN { character: "Henry Fitzpatrick", order: 2 }]->(:Movie)
```

### Indexes

```cypher
CREATE CONSTRAINT actor_id  FOR (a:Actor) REQUIRE a.person_id IS UNIQUE;
CREATE CONSTRAINT movie_id  FOR (m:Movie) REQUIRE m.movie_id  IS UNIQUE;
CREATE INDEX actor_rank     FOR (a:Actor) ON (a.rank);
CREATE INDEX movie_votes    FOR (m:Movie) ON (m.vote_count);
CREATE FULLTEXT INDEX actorNames  FOR (a:Actor) ON EACH [a.name];
CREATE FULLTEXT INDEX movieTitles FOR (m:Movie) ON EACH [m.title];
```

---

## Core Queries

### Shortest path (for `/game` validation and `/solve`)

```cypher
MATCH p = shortestPath(
  (a1:Actor {person_id: $source})-[:APPEARED_IN*..12]-(a2:Actor {person_id: $target})
)
RETURN length(p) AS hops
```

### All shortest paths (for `/solve`, capped at 10)

```cypher
MATCH p = allShortestPaths(
  (a1:Actor {person_id: $source})-[:APPEARED_IN*..12]-(a2:Actor {person_id: $target})
)
RETURN [n IN nodes(p) | CASE labels(n)[0]
  WHEN 'Actor' THEN {id: n.person_id, name: n.name,  type: 'actor',  image: n.profile_path}
  WHEN 'Movie' THEN {id: n.movie_id,  title: n.title, type: 'movie', image: n.poster_path}
END] AS path
LIMIT 10
```

### Autocomplete

```cypher
CALL db.index.fulltext.queryNodes('actorNames', $query + '*')
YIELD node, score
RETURN node.person_id, node.name, node.popularity, node.profile_path
ORDER BY node.popularity DESC LIMIT 10
```

### Neighbor-constrained autocomplete

```cypher
MATCH (m:Movie {movie_id: $movie_id})<-[:APPEARED_IN]-(a:Actor)
WHERE toLower(a.name) CONTAINS toLower($query)
RETURN a.person_id, a.name, a.popularity, a.profile_path
ORDER BY a.popularity DESC LIMIT 20
```

---

## Backend Changes

### Removed
- `GraphStore` singleton (NetworkX + pickle)
- Custom `Trie` autocomplete
- `graph.pkl` build artifact
- ~15–30s cold start time
- 1–2 GB RAM graph footprint

### Added

```python
# app/db.py  (Phase 2 — implemented)
from neo4j import AsyncGraphDatabase
from settings import settings

def get_driver():
    return AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
```

API starts in ~1 second. Stateless — any number of instances can run against the same Neo4j.

### Endpoint mapping

| Endpoint | v1 | Phase 2 (current) | Production |
|---|---|---|---|
| `GET /game` | Python BFS, 50-retry loop | Cypher `shortestPath` over rank-bounded random pool | Redis pair pool pop; Cypher fallback |
| `POST /validate` | NetworkX edge lookup | Cypher `OPTIONAL MATCH` via `UNWIND` | Unchanged |
| `POST /solve` | Custom all-paths DFS | Cypher `allShortestPaths()` | Unchanged |
| `GET /autocomplete` | Custom Trie | Neo4j full-text index (`actorNames` / `movieTitles`) | Unchanged |
| `GET /autocomplete/neighbors` | NetworkX neighbors + Trie | Neo4j neighbor query with optional substring filter | Unchanged |
| `GET /connected` | NetworkX edge check | Cypher `EXISTS` — checks actor+movie APPEARED_IN edge | Unchanged |

Request/response shapes preserved; `source_nconst`/`target_nconst` renamed to `source_id`/`target_id` (now TMDB integer strings).

---

## Caching (Redis)

| Key pattern | TTL | Value |
|---|---|---|
| `pair_pool:{difficulty}` | 1h | List of 100 pre-vetted `{source, target}` pairs |
| `solve:{source}:{target}` | 24h | Serialized all-paths result |
| `autocomplete:actor:{q}` | 1h | Top-10 actor results |

---

## Images

TMDB provides relative paths (`/abc.jpg`). Full URL: `https://image.tmdb.org/t/p/{size}{path}`.

- Actor thumbnails: `w185`
- Movie posters: `w342`

Serve TMDB image URLs directly from the frontend in the first iteration. Proxy to Cloudflare R2 later if reliability becomes an issue.

---

## Infrastructure

### Services

| Service | Where | Cost |
|---|---|---|
| Neo4j Community Edition | GCP Compute Engine e2-highmem-2 (2 vCPU, 16 GB RAM) | ~$48/mo |
| Persistent disk (100 GB SSD) | Attached to Neo4j VM | ~$17/mo |
| Static IP | GCP reserved | ~$7/mo |
| Redis | Same VM via Docker Compose | $0 |
| FastAPI | Cloud Run (stateless, VPC Direct Egress → VM) | ~$0–10/mo |
| React frontend | Cloudflare Pages | Free |
| **Total** | | **~$75/mo** |

Neo4j software is free (Community Edition). No AuraDB — AuraDB Professional costs ~$65/GB/month, putting this dataset at $650–975/mo.

### Docker Compose

Neo4j and Redis run on the GCP VM via Docker Compose, internal-only (no external ports). FastAPI runs on Cloud Run and connects to the VM via VPC Direct Egress — no Nginx needed on the VM.

### Data Safety

GCP Persistent Disk is a separate resource from the VM — it survives VM deletion or recreation by default. Add a GCP snapshot schedule (daily, 7-day retention) for point-in-time recovery. This is equivalent to managed backup at effectively zero cost.

### CI/CD

Two GitHub Actions workflows:

- **`.github/workflows/ci.yml`** — runs on every PR. `backend-test` spins up `neo4j:5-community` as a service container and runs the pytest suite against it. `frontend-build` runs `npm run build` (TypeScript + Vite) to catch type errors. Also exposed as a reusable workflow.
- **`.github/workflows/deploy.yml`** — runs on push to `main`. Re-runs CI, then `gcloud builds submit` produces an image tagged with both `:${commit-sha}` and `:latest`, then `gcloud run services update` rolls the Cloud Run service and `gcloud run jobs update` rolls the `connactor-pipeline-full` job to the same SHA-pinned digest. SHA tags enable trivial rollback.

Authentication uses Workload Identity Federation (no static JSON keys in GitHub secrets). GitHub's OIDC token is exchanged for a short-lived GCP token that impersonates the existing `connactor-api` service account. One-time setup is in [`docs/ops/setup-wif.md`](./ops/setup-wif.md).

Frontend deploys via Cloudflare Pages on push to `main` (separate from the GitHub Actions deploy workflow — Cloudflare watches the GitHub repo directly). Neo4j on the VM is not touched by CI/CD — updated separately via the bootstrap pipeline.

### Custom domains

- `https://connactor.com` → Cloudflare Pages (proxied through Cloudflare's CDN, automatic Universal SSL)
- `https://api.connactor.com` → Cloud Run service via [domain mapping](https://cloud.google.com/run/docs/mapping-custom-domains) (DNS-only CNAME to `ghs.googlehosted.com`, Google-managed SSL)

Setup is captured in [`docs/ops/setup-cloudflare.md`](./ops/setup-cloudflare.md). The frontend bakes `VITE_API_URL=https://api.connactor.com` into the bundle at build time via Cloudflare Pages environment variables.

### Cost + usage monitoring

A daily Cloud Run Job (`connactor-cost-report`, triggered every day at 14:00 UTC by Cloud Scheduler) builds a single HTML email summarising the rolling 7-day window vs the week before. Three data sources, one Resend POST:

- **GCP cost** — BigQuery query against the detailed billing export (`connactor-497019.billing_export.gcp_billing_export_resource_v1_*`). Net of credits, grouped by service.
- **Cloudflare cost** — `GET /accounts/{id}/subscriptions`, summed and prorated to a weekly equivalent.
- **Usage** — Cloudflare GraphQL Analytics API (`httpRequests1dGroups`) for daily uniques + pageviews. Cumulative since launch is a separate query from `LAUNCH_DATE` (2026-05-23). No app instrumentation — Cloudflare collects at the edge.

Anything >25% WoW (cost ↑ or visitors ↓) gets visually flagged. Reuses the existing job/scheduler/SA pattern from the data pipeline — no new infra class. Setup runbook: [`docs/ops/setup-cost-report.md`](./ops/setup-cost-report.md).

---

## Migration Path

| Phase | Work | Goal |
|---|---|---|
| 1 | TMDB crawler + Neo4j data model + bulk loader | Graph DB running locally with full dataset |
| 2 | FastAPI Neo4j driver + Cypher queries replace BFS + Trie | All endpoints backed by Neo4j, tests green |
| 3 | Redis pair pool + daily/hourly cron jobs | Reliable pair generation, solve caching |
| 4 | GCP VM setup + Docker Compose + CI/CD | Production deployed |
| 5 | TMDB images in API responses + NodeChip UI | Actor/movie art in frontend |
| 6 | Auth + leaderboards (Postgres) | v2 multiplayer foundation |
