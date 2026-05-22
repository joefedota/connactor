# Connactor

Connect two actors through shared movies in as few hops as possible.

---

## Prerequisites

| Tool | Install |
|------|---------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Required for local Neo4j |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Python package manager |
| [gcloud CLI](https://cloud.google.com/sdk/docs/install) | GCS access + ADC auth |
| TMDB API key | Free at [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) — get the **Read Access Token** |

---

## GCP Setup (one-time)

All pipeline artifacts (crawled data, Neo4j dumps) live in the shared `connactor-data` GCS bucket in project `connactor-497019`. Ask the project owner for access, then authenticate:

```bash
gcloud auth application-default login
gcloud config set project connactor-497019
```

---

## Local Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/joefedota/connactor.git
cd connactor/backend
uv sync
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `backend/.env` and fill in:

```
TMDB_API_READ_TOKEN=your_tmdb_read_access_token
NEO4J_PASSWORD=connactorpassword   # or whatever you prefer
GCS_BUCKET=connactor-data
```

`NEO4J_URI`, `NEO4J_USER` default to `bolt://localhost:7687` / `neo4j` and don't need to be changed for local dev.

### 3. Start Neo4j

```bash
# From the repo root:
docker compose up -d neo4j
```

Neo4j is available at:
- **Bolt** (driver): `bolt://localhost:7687`
- **Browser UI**: http://localhost:7474 (user: `neo4j`, password: whatever you set in `.env`)

### 4. Bootstrap the graph

Run the dev bootstrap — downloads the TMDB movie export, crawls the top 1,000 movies, enriches actor metadata, and loads everything into Neo4j. Takes ~15 minutes.

```bash
cd backend
uv run python pipeline/bootstrap.py --mode dev
```

Each step is idempotent. If it fails mid-run, re-run the same command and it resumes from the GCS checkpoint. To skip steps you've already completed:

```bash
uv run python pipeline/bootstrap.py --mode dev --skip-download --skip-credits --skip-persons
```

For the full production dataset (~35k movies, ~4–6 hours):
```bash
uv run python pipeline/bootstrap.py --mode prod
```

### 5. Verify the graph

```bash
docker exec connactor-neo4j-dev cypher-shell -u neo4j -p connactorpassword \
  "MATCH (a:Actor) RETURN count(a) AS actors;
   MATCH (m:Movie) RETURN count(m) AS movies;
   MATCH ()-[r:APPEARED_IN]->() RETURN count(r) AS edges;"
```

Spot-check a path:
```bash
docker exec connactor-neo4j-dev cypher-shell -u neo4j -p connactorpassword \
  "MATCH p = shortestPath((a1:Actor)-[:APPEARED_IN*..12]-(a2:Actor))
   WHERE a1.rank < 10 AND a2.rank < 10 AND a1 <> a2
   RETURN [n IN nodes(p) | coalesce(n.name, n.title)] AS path LIMIT 3;"
```

### 6. Publish a dev seed (optional)

Once the graph is loaded, dump it to GCS so other developers can skip the bootstrap entirely:

```bash
./backend/bin/dump-neo4j.sh dev
```

Other developers can then restore in seconds instead of re-crawling:

```bash
./backend/bin/setup-local-neo4j.sh dev
```

---

## Running the App

> **Note:** The FastAPI backend and React frontend are not yet connected to Neo4j (Phase 2). The current API still reads from the legacy IMDB/NetworkX graph. Instructions will be updated once Phase 2 is complete.

---

## Running Tests

```bash
cd backend
uv run pytest
```

---

## Project Structure

```
connactor/
  backend/
    app/              # FastAPI application (Phase 2: will connect to Neo4j)
    bin/              # Shell scripts (dump/restore Neo4j)
    migrations/       # Neo4j schema (constraints + indexes)
    pipeline/         # Python data pipeline
      bootstrap.py    # One-command pipeline orchestrator
      ingest/         # TMDB crawlers + Neo4j loader
    utils/            # Shared Python utilities (GCS helpers)
    settings.py       # Pydantic settings (reads from .env)
    tests/
  frontend/           # React + TypeScript + Vite
  docker-compose.yml  # Local Neo4j
```

---

## Architecture

See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for the full production architecture.

**Short version:**

```
TMDB API → async crawler → GCS (JSONL) → Neo4j loader → Neo4j
                                                           ↓
                                               FastAPI (Cloud Run)
                                                           ↓
                                            React (Cloudflare Pages)
```

Graph model: `(:Actor)-[:APPEARED_IN]->(:Movie)`. Shortest path via Cypher `shortestPath()`. Full-text indexes for autocomplete.
