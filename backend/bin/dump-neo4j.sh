#!/usr/bin/env bash
# dump-neo4j.sh [dev|prod]
# Dumps the local Neo4j database and uploads the dump to GCS.
# Neo4j must be running via docker compose before calling this.

set -euo pipefail

MODE=${1:-dev}
if [[ "$MODE" != "dev" && "$MODE" != "prod" ]]; then
  echo "Usage: $0 [dev|prod]"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DUMPS_DIR="$REPO_ROOT/data/dumps"
DUMP_FILE="$DUMPS_DIR/neo4j-seed-${MODE}.dump"
GCS_BLOB="dumps/neo4j-seed-${MODE}.dump"

mkdir -p "$DUMPS_DIR"

echo "=== Connactor Neo4j Dump (mode=$MODE) ==="

echo "  Stopping Neo4j ..."
docker compose -f "$REPO_ROOT/docker-compose.yml" stop neo4j

echo "  Dumping database ..."
docker compose -f "$REPO_ROOT/docker-compose.yml" run --rm neo4j \
  neo4j-admin database dump neo4j --to-path=/dumps --overwrite-destination=true

# neo4j-admin dump writes to /dumps/neo4j.dump inside the container
mv "$DUMPS_DIR/neo4j.dump" "$DUMP_FILE"
echo "  Dump written to: $DUMP_FILE"

echo "  Restarting Neo4j ..."
docker compose -f "$REPO_ROOT/docker-compose.yml" start neo4j

echo "  Uploading to GCS: $GCS_BLOB"
cd "$REPO_ROOT/backend"
uv run python -c "
import sys; sys.path.insert(0, '.')
from utils.gcs import upload_from_file
from pathlib import Path
upload_from_file(Path('$DUMP_FILE'), '$GCS_BLOB')
print('  Upload complete.')
"

echo "=== Dump complete: gs://\${GCS_BUCKET:-connactor-data}/$GCS_BLOB ==="
