#!/usr/bin/env bash
# generate-daily-puzzle.sh [dev|prod] [--date YYYY-MM-DD]
# Runs pipeline/generate_daily_puzzle.py against the local (dev) or Neon (prod) database.
# For prod, DATABASE_URL is fetched from GCP Secret Manager.
# All additional args (e.g. --date) are forwarded to the Python script.
#
# Usage:
#   backend/bin/generate-daily-puzzle.sh              # dev, defaults to tomorrow
#   backend/bin/generate-daily-puzzle.sh dev
#   backend/bin/generate-daily-puzzle.sh dev --date 2026-05-25
#   backend/bin/generate-daily-puzzle.sh prod
#   backend/bin/generate-daily-puzzle.sh prod --date 2026-05-25

set -euo pipefail

MODE=${1:-dev}
if [[ "$MODE" != "dev" && "$MODE" != "prod" ]]; then
  echo "Usage: $0 [dev|prod] [--date YYYY-MM-DD]"
  exit 1
fi
shift  # remove mode from args; pass the rest to the Python script

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

echo "=== Generating daily puzzle (mode=$MODE) ==="
cd "$BACKEND_DIR"
DATABASE_URL="$DATABASE_URL" uv run python pipeline/generate_daily_puzzle.py "$@"
echo "=== Done ==="
