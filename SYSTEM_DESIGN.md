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
              └─► FastAPI backend (stateless)
                    └─► Redis (pair pool + solve cache)
                          └─► React frontend (Cloudflare Pages)
```

---

## Data Pipeline

### Initial Full Load (~4–6 hours, run once)

1. Download TMDB daily movie ID export (`files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz`)
2. Filter to `vote_count > 50` and `popularity > 1.0` (~150–200k qualifying movies)
3. Async crawl `/movie/{id}/credits` at ~40 req/s for all qualifying movies
4. Async crawl `/person/{id}` for all unique person IDs
5. Bulk load into Neo4j via Python neo4j driver using `MERGE` in batches (idempotent; re-runnable)

### Daily Delta Refresh (cron, 9 AM UTC)

1. `GET /movie/changes?start_date={yesterday}&end_date={today}` — returns ~1–5k changed movie IDs
2. Re-crawl `/movie/{id}/credits` for each changed movie
3. MERGE new nodes/edges into Neo4j, remove stale edges

### Hourly Pair Pool Refresh (cron)

Pre-generate 100 valid actor pairs per difficulty tier and store in Redis. Eliminates the 50-retry BFS loop from v1.

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
# app/db.py
from neo4j import AsyncGraphDatabase
import redis.asyncio as redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.neo4j = AsyncGraphDatabase.driver(NEO4J_URI, auth=(USER, PASS))
    app.state.redis = redis.from_url(REDIS_URL)
    yield
    await app.state.neo4j.close()
    await app.state.redis.close()
```

API starts in ~1 second. Stateless — any number of instances can run against the same Neo4j.

### Endpoint mapping

| Endpoint | v1 | Production |
|---|---|---|
| `GET /game` | Python BFS, 50-retry loop | Redis pair pool pop; Neo4j fallback |
| `POST /validate` | NetworkX edge lookup | Neo4j EXISTS check |
| `POST /solve` | Custom all-paths DFS | Neo4j `allShortestPaths()` |
| `GET /autocomplete` | Custom Trie | Neo4j full-text index |
| `GET /autocomplete/neighbors` | NetworkX neighbors + Trie | Neo4j neighbor query |
| `GET /connected` | NetworkX edge check | Neo4j EXISTS check |

All request/response shapes are identical — no frontend changes required.

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

GitHub Actions: run tests → build API container → push to Artifact Registry → deploy to Cloud Run. Frontend: Cloudflare Pages watches `main` and deploys automatically. Neo4j on the VM is not touched by CI/CD — updated separately via the bootstrap pipeline.

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
