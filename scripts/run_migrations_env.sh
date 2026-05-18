#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  echo "Error: .env file not found. Copy .env.example to .env and fill in your Supabase values."
  exit 1
fi

set -a
. .env
set +a

if [ -z "${SUPABASE_DB_URL:-}" ]; then
  echo "Error: SUPABASE_DB_URL is not set in .env."
  exit 1
fi

shopt -s nullglob
for f in db/migrations/*.sql; do
  echo "Applying migration: $f"
  psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f "$f"
done

echo "All migrations applied."
