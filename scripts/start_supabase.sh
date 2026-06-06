#!/bin/bash
# ── Supabase Local Dev Stack Startup Script ──────────────────────────────
# Run this from the mt5 bot/ project root.
# Prerequisites: Docker Desktop running, supabase CLI installed.
#
# Usage:
#   bash scripts/start_supabase.sh          # start + link
#   bash scripts/start_supabase.sh --stop   # stop the stack
# =========================================================================

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "──────────────────────────────────────────────"
echo "  mt5_bot — Supabase Local Dev"
echo "──────────────────────────────────────────────"

# ── Check Docker ──────────────────────────────────────────────────────────
if ! docker ps > /dev/null 2>&1; then
  echo "❌ Docker is not running."
  echo "   Start Docker Desktop first, then retry."
  exit 1
fi
echo "✅ Docker running"

# ── Check Supabase CLI ────────────────────────────────────────────────────
if ! command -v supabase &>/dev/null; then
  echo "❌ supabase CLI not found. Install: npm install -g supabase"
  exit 1
fi
echo "✅ supabase CLI: $(supabase --version)"

# ── Action ────────────────────────────────────────────────────────────────
case "${1:-start}" in
  start)
    echo "🚀 Starting local Supabase stack..."
    supabase start
    echo ""
    echo "📦 Services running on:"
    echo "   API:      http://127.0.0.1:54321"
    echo "   DB:       postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    echo "   Studio:   http://127.0.0.1:54323"
    echo "   Inbucket: http://127.0.0.1:54324 (email testing)"
    echo ""
    echo "🔗 Link to remote project (run once):"
    echo "   supabase link --project-ref <your-project-ref>"
    echo ""
    echo "📊 To push migrations:"
    echo "   supabase db push"
    echo ""
    echo "📋 To see services: supabase status"
    ;;

  stop)
    echo "🛑 Stopping local Supabase stack..."
    supabase stop
    echo "✅ Stopped"
    ;;

  status)
    supabase status
    ;;

  reset)
    echo "🔄 Resetting local database (applies migrations + seed)..."
    supabase db reset
    echo "✅ Reset complete"
    ;;

  *)
    echo "Usage: $0 [start|stop|status|reset]"
    exit 1
    ;;
esac
