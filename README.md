# Connactor

Connect two actors through shared movies in as few hops as possible.

## Setup

### 1. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Download IMDB data + build graph (~10 min, ~1 GB download)

```bash
cd backend
python scripts/ingest.py
```

This downloads three IMDB bulk TSV files and writes:
- `data/processed/graph.pkl` — NetworkX bipartite graph (~1–2 GB RAM)
- `data/processed/actor_index.json`
- `data/processed/movie_index.json`

### 3. Pre-generate puzzle pairs

```bash
python scripts/generate_pairs.py
```

Writes `data/processed/pairs.json` (1000 actor pairs, paths 2–6 hops).

### 4. Start the API server

```bash
cd backend
uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`. First load takes ~15–30 seconds while the graph deserializes.

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend at `http://localhost:5173`. API calls proxied to `localhost:8000` via Vite.

## Run tests

```bash
cd backend
python -m pytest tests/ -v
```

## API reference

| Endpoint | Description |
|----------|-------------|
| `GET /game` | Random actor pair |
| `POST /validate` | Validate path `{source_nconst, target_nconst, path: [id, ...]}` |
| `POST /solve` | All optimal paths `{source_nconst, target_nconst}` |
| `GET /autocomplete?q=...&type=actor\|movie` | Prefix search |
| `GET /autocomplete/neighbors?node_id=...&type=actor\|movie` | Constrained neighbor search |
| `GET /health` | Graph stats |

## Architecture

- **Graph**: NetworkX bipartite graph loaded in-memory. Actor nodes (`nm...`) ↔ Movie nodes (`tt...`). Edges = appeared in.
- **BFS**: Finds shortest path length + enumerates all optimal paths (DFS with backward-BFS pruning, capped at 10).
- **Autocomplete**: Two tries (actors + movies) with diacritic normalization. Word-level indexing lets users type last names.
- **Chain UX**: Search alternates actor/movie by path position parity. Neighbor-constrained search means only valid moves are shown.
