# Developer Onboarding Runbook

Steps for the project owner (Joe) to grant access, and for the new developer to get a working local environment.

---

## Step 1 — Project owner grants access

### GitHub
Go to **github.com/joefedota/connactor → Settings → Collaborators → Add people** and invite by GitHub username. Set role to **Write** (can push branches, open PRs) or **Admin** (can also manage settings).

### Google Cloud
```bash
gcloud projects add-iam-policy-binding connactor-497019 \
  --member="user:THEIR_EMAIL@gmail.com" \
  --role="roles/owner"
```

This gives access to: Cloud Run, Artifact Registry, Secret Manager, Cloud Scheduler, Compute Engine (Neo4j VM), GCS, and logs.

---

## Step 2 — New developer: get credentials

### TMDB API key
Get your own free key at [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api). Use the **Read Access Token** (the long JWT, not the short API key).

### GCP auth
```bash
gcloud auth application-default login
gcloud config set project connactor-497019
```

This gives your local machine access to the `connactor-data` GCS bucket (pipeline artifacts and Neo4j dumps).

---

## Step 3 — New developer: local setup

Follow **[README.md](../../README.md)** for full local setup. The short version:

```bash
git clone https://github.com/joefedota/connactor.git
cd connactor

# Install backend deps
cd backend && uv sync && cd ..

# Copy and fill in env vars
cp backend/.env.example .env
# Edit .env: set TMDB_API_READ_TOKEN to your key; leave everything else as-is for local dev

# Start Neo4j + Postgres
docker compose up -d

# Run Postgres migrations
cd backend && uv run alembic upgrade head && cd ..

# Load the Neo4j graph (fastest: restore from pre-built dump, ~2 min)
./backend/bin/setup-local-neo4j.sh dev

# Start the backend
cd backend && uv run uvicorn app.main:app --reload --port 8000

# In another terminal: start the frontend
cd frontend && npm install && npm run dev
```

Set the API URL for the frontend:
```bash
echo "VITE_API_URL=http://localhost:8000" > frontend/.env.local
```

App runs at http://localhost:5173, API at http://localhost:8000.

---

## Key systems

| System | What it is | How to access |
|--------|-----------|---------------|
| **GitHub** | Source, PRs, CI | github.com/joefedota/connactor |
| **GCP project** | All cloud infrastructure | console.cloud.google.com — project `connactor-497019` |
| **Cloud Run** | Production API (`connactor-api`) | GCP console → Cloud Run |
| **Neo4j VM** | Graph database at `10.128.0.2:7687` | GCP console → Compute Engine → `connactor-neo4j` |
| **Neon Postgres** | Production relational DB | `DATABASE_URL` secret in Secret Manager |
| **Artifact Registry** | Docker images | `us-central1-docker.pkg.dev/connactor-497019/connactor/api` |
| **GCS bucket** | Pipeline data + Neo4j dumps | `gs://connactor-data` |
| **Cloudflare Pages** | Frontend hosting | Cloudflare dashboard (ask Joe for access) |

---

## Deployment

Merging to `main` auto-deploys the backend via GitHub Actions (`.github/workflows/deploy.yml`). The frontend deploys separately via Cloudflare Pages.

To deploy manually or roll back, see [setup-cloudrun.md](setup-cloudrun.md).

---

## Workflow

One issue → one branch → one PR. See [CLAUDE.md](../../CLAUDE.md) for the full branch naming and PR template conventions.

```bash
git checkout main && git pull
git checkout -b feature/issue-{number}-{short-description}
# ... make changes ...
gh pr create
```

Never commit directly to `main`.
