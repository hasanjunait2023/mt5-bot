#!/usr/bin/env bash

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required. Install from https://nodejs.org/."
  exit 1
fi

if ! command -v supabase >/dev/null 2>&1; then
  echo "Installing supabase CLI..."
  npm install -g supabase
fi

if [ ! -d ".supabase" ]; then
  echo "Initializing supabase project..."
  supabase init
fi

echo "Starting supabase local stack..."
supabase start
