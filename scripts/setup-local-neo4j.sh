#!/usr/bin/env bash
# setup-local-neo4j.sh [dev|prod]
# Sets up local Neo4j from a GCS dump (fast path) or runs full bootstrap (slow path).

set -euo pipefail

MODE=${1:-dev}
if [[ "$MODE" != "dev" && "$MODE" != "prod" ]]; then
  echo "Usage: $0 [dev|prod]"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMPS_DIR="$REPO_ROOT/data/dumps"
GCS_BLOB="dumps/neo4j-seed-${MODE}.dump"

mkdir -p "$DUMPS_DIR"

echo "=== Connactor Neo4j Setup (mode=$MODE) ==="

# Check if a GCS dump exists
cd "$REPO_ROOT/backend"
DUMP_EXISTS=$(uv run python -c "
import sys; sys.path.insert(0, 'scripts')
from ingest.gcs import blob_exists
print('yes' if blob_exists('$GCS_BLOB') else 'no')
")

if [[ "$DUMP_EXISTS" == "yes" ]]; then
  echo "  Dump found in GCS: $GCS_BLOB"
  echo "  Downloading ..."
  uv run python -c "
import sys; sys.path.insert(0, 'scripts')
from ingest.gcs import download_to_file
from pathlib import Path
download_to_file('$GCS_BLOB', Path('$DUMPS_DIR/neo4j.dump'))
print('  Downloaded.')
"

  echo "  Stopping Neo4j ..."
  docker compose -f "$REPO_ROOT/docker-compose.yml" stop neo4j

  echo "  Loading dump ..."
  docker compose -f "$REPO_ROOT/docker-compose.yml" run --rm neo4j \
    neo4j-admin database load neo4j --from-path=/dumps --overwrite-destination=true

  echo "  Starting Neo4j ..."
  docker compose -f "$REPO_ROOT/docker-compose.yml" start neo4j

  echo "=== Setup complete (loaded from GCS dump) ==="
else
  echo "  No GCS dump found for mode=$MODE — running full bootstrap ..."
  docker compose -f "$REPO_ROOT/docker-compose.yml" up -d neo4j
  echo "  Waiting for Neo4j to be ready ..."
  sleep 10
  uv run python scripts/bootstrap.py --mode "$MODE"
  echo "=== Setup complete (bootstrapped from TMDB) ==="
fi
