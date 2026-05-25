#!/usr/bin/env bash
# migrate.sh [dev|prod]
# Runs alembic upgrade head against the local (dev) or Neon (prod) Postgres database.
#
# Usage:
#   backend/bin/migrate.sh         # defaults to dev
#   backend/bin/migrate.sh dev
#   backend/bin/migrate.sh prod

set -euo pipefail

MODE=${1:-dev}
if [[ "$MODE" != "dev" && "$MODE" != "prod" ]]; then
  echo "Usage: $0 [dev|prod]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/.."

if [[ "$MODE" == "prod" ]]; then
  echo "=== Fetching DATABASE_URL from Secret Manager ==="
  DATABASE_URL="$(gcloud secrets versions access latest \
    --secret=DATABASE_URL \
    --project=connactor-497019)"
  echo "  Target: $(echo "$DATABASE_URL" | sed 's|//[^@]*@|//<credentials>@|')"
else
  DATABASE_URL="postgresql+asyncpg://connactor:connactorpassword@localhost:5432/connactor"
  echo "=== Using local DATABASE_URL ==="
fi

echo "=== Running: alembic upgrade head (mode=$MODE) ==="
cd "$BACKEND_DIR"
DATABASE_URL="$DATABASE_URL" uv run alembic upgrade head
echo "=== Migration complete ==="
