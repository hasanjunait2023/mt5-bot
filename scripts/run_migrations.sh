#!/usr/bin/env bash
set -euo pipefail

if [ -z "${SUPABASE_DB_URL:-}" ]; then
  echo "Error: SUPABASE_DB_URL environment variable is not set.\nSet it to your Supabase Postgres connection string (e.g. postgresql://user:pass@host:port/db)"
  exit 1
fi

shopt -s nullglob
for f in db/migrations/*.sql; do
  echo "Applying migration: $f"
  psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f "$f"
done

echo "All migrations applied."
