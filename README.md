# Connactor

Connect two actors through shared movies in as few hops as possible.

**Live**: https://connactor.com — API at https://api.connactor.com

---

## Prerequisites

| Tool | Install |
|------|---------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Required for local Neo4j + Postgres |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Python package manager |
| [Node.js 18+](https://nodejs.org/) | Required for the frontend |
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

The backend reads from a `.env` file at the **repo root** (one level above `backend/`):

```bash
cp backend/.env.example .env   # from repo root
```

Edit `.env` and fill in at minimum:

```
TMDB_API_READ_TOKEN=your_tmdb_read_access_token
NEO4J_PASSWORD=connactorpassword

# Local Postgres (docker compose) — no change needed for local dev
DATABASE_URL=postgresql+asyncpg://connactor:connactorpassword@localhost:5432/connactor

# Any string works locally; use a real secret in prod
COOKIE_SECRET=local-dev-secret
```

`NEO4J_URI`, `NEO4J_USER` default to `bolt://localhost:7687` / `neo4j` and don't need to be changed for local dev.

### 3. Start the databases

```bash
# From the repo root — starts both Neo4j and Postgres:
docker compose up -d
```

Services:
| Service | URL / port |
|---------|------------|
| Neo4j Bolt | `bolt://localhost:7687` |
| Neo4j Browser | http://localhost:7474 (user: `neo4j`, password from `.env`) |
| Postgres | `localhost:5432` (user: `connactor`, db: `connactor`) |

### 4. Run database migrations

```bash
cd backend
uv run alembic upgrade head
```

This creates the `users`, `puzzles`, and `game_completions` tables in local Postgres.

### 5. Bootstrap the Neo4j graph

Run the dev bootstrap — downloads the TMDB movie export, crawls the top 1,000 movies, enriches actor metadata, and loads everything into Neo4j. Takes ~15 minutes.

```bash
cd backend
uv run python pipeline/bootstrap.py --mode dev
```

Each step is idempotent. If it fails mid-run, re-run the same command and it resumes from the GCS checkpoint. To skip steps you've already completed:

```bash
uv run python pipeline/bootstrap.py --mode dev --skip-download --skip-credits --skip-persons
```

**Shortcut** — restore from a pre-built dump instead of re-crawling:

```bash
./backend/bin/setup-local-neo4j.sh dev
```

For the full production dataset (~35k movies, ~4–6 hours):

```bash
uv run python pipeline/bootstrap.py --mode prod
```

### 6. Verify the graph

```bash
docker exec connactor-neo4j-dev cypher-shell -u neo4j -p connactorpassword \
  "MATCH (a:Actor) RETURN count(a) AS actors;
   MATCH (m:Movie) RETURN count(m) AS movies;
   MATCH ()-[r:APPEARED_IN]->() RETURN count(r) AS edges;"
```

---

## Running the App

### Backend

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

API available at http://localhost:8000. Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/game` | Random actor pair |
| GET | `/daily` | Today's daily puzzle + your completion status |
| POST | `/complete` | Record a game completion |
| POST | `/solve` | Optimal paths between two actors |
| GET | `/health` | Graph stats |

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend available at http://localhost:5173. Set the backend URL:

```bash
# frontend/.env.local
VITE_API_URL=http://localhost:8000
```

Both should be running at the same time for the full experience.

---

## Daily Challenge (local testing)

Generate today's puzzle manually (the production job runs at 06:00 UTC):

```bash
cd backend
uv run python bin/generate_daily_puzzle.py --date $(date +%Y-%m-%d)
```

Then visit http://localhost:5173/daily.

---

## Running Tests

```bash
cd backend
uv run pytest
```

Tests require a running local Neo4j (`docker compose up -d neo4j`). The same suite runs in CI against a `neo4j:5-community` service container.

---

## Deployment

Push to `main` triggers `.github/workflows/deploy.yml`:

1. CI reruns (backend pytest against a Neo4j service container, frontend `npm run build`).
2. `gcloud builds submit` builds the backend Docker image and tags it `:${commit-sha}` and `:latest` in Artifact Registry.
3. The Cloud Run service `connactor-api` is rolled to the new SHA-pinned image.

Authentication uses Workload Identity Federation — no JSON keys are stored in GitHub secrets. See [`docs/ops/setup-wif.md`](docs/ops/setup-wif.md) for one-time setup.

**Applying migrations to production (Neon):**

```bash
DATABASE_URL="postgresql+asyncpg://<neon-url>?ssl=require" uv run alembic upgrade head
```

Only run this after verifying the migration works locally.

To roll back the API:

```bash
gcloud run services update connactor-api \
  --project connactor-497019 --region us-central1 \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:<old-sha>
```

---

## Project Structure

```
connactor/
  backend/
    alembic/            # Postgres migration scripts
    app/
      main.py           # FastAPI app + all endpoints
      models.py         # Pydantic request/response models
      db.py             # Neo4j async driver
      pg.py             # Postgres async SQLAlchemy session
      middleware/
        user_identity.py  # Anonymous cookie identity
    bin/
      generate_daily_puzzle.py  # Cloud Run Job: pre-generate tomorrow's daily pair
    migrations/         # Neo4j schema (constraints + indexes)
    pipeline/           # TMDB data pipeline
      bootstrap.py      # One-command pipeline orchestrator
      ingest/           # TMDB crawlers + Neo4j loader
    settings.py         # Pydantic settings (reads from root .env)
    tests/
  frontend/
    src/
      api/client.ts     # All API calls
      screens/          # Home, GameBoard, Results, Daily
      store/gameStore.ts
      types/index.ts
  docker-compose.yml    # Local Neo4j + Postgres
```

---

## Architecture

See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for the full production architecture.

```
TMDB API → async crawler → GCS (JSONL) → Neo4j loader → Neo4j (graph)
                                                            ↓
                                               FastAPI (Cloud Run)
                                                ↙           ↘
                                  Postgres/Neon          Neo4j
                              (users, puzzles,        (graph queries,
                               completions)            autocomplete)
                                                            ↓
                                            React (Cloudflare Pages)
```
