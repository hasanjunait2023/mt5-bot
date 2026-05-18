% Supabase Setup and Usage

This document describes how to install and use Supabase for this project's database. The recommended path is Hosted Supabase Cloud; local Docker is only required if you want an offline/local stack.

## Quick overview
- Hosted: create a project at https://app.supabase.com/ (recommended)
- Local dev: use the Supabase CLI + Docker only when you need a local instance

## Prerequisites
- Git
- Node.js (for installing the Supabase CLI via `npm`) or `scoop` on Windows
- Docker only for local development

## Hosted Supabase (recommended)
1. Create a project at https://app.supabase.com/.
2. Copy the project settings:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
3. In Project Settings > Database > Connection info, copy the Postgres connection string.
4. Create a local `.env` from `.env.example` and add all values.
5. Run your app using the hosted Supabase credentials. You do not need Docker or `supabase start` for hosted usage.

## Local Supabase only if needed
For developers who need an offline/local dev stack, install Docker Desktop and use the Supabase CLI:

```bash
npm install -g supabase
supabase init
supabase start
```

Local Docker is optional. If you do not want Docker installed, use Hosted Supabase and run your app against the remote project.

## Install Supabase CLI (Windows)
Option A — npm (portable):

```bash
npm install -g supabase
```

Option B — Scoop (Windows):

```powershell
scoop install supabase
```

The CLI is useful for applying migrations and remote schema commands, but it is not required to use hosted Supabase if you already have the connection string and keys.

## Environment variables
Add these to your environment (see `.env.example` in repo):

- `SUPABASE_URL` — your project URL
- `SUPABASE_ANON_KEY` — anon/public key
- `SUPABASE_SERVICE_ROLE_KEY` — server key (keep secret)
- `SUPABASE_DB_URL` — Postgres connection string for migrations

Never commit `SUPABASE_SERVICE_ROLE_KEY` or any real keys to Git. Store them in your secret manager or CI settings.

## Schema and migrations
- For hosted Supabase, use the remote DB connection string and apply migrations with the scripts in `scripts/`.
- For repeatable migrations, store SQL files under `db/migrations/` and apply them consistently across environments.

Example minimal schema (users + trades):

```sql
create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text unique,
  created_at timestamptz default now()
);

create table if not exists trades (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  symbol text,
  size numeric,
  direction text,
  opened_at timestamptz default now()
);
```

### Apply hosted migrations
If you have a hosted Supabase project and `SUPABASE_DB_URL` set, run:

```bash
./scripts/run_migrations.sh
```

If you store your hosted connection info in `.env`, use the new helper:

```bash
./scripts/run_migrations_env.sh
```

Or run via npm:

```bash
npm run migrate:hosted
```

On Windows PowerShell:

```powershell
$env:SUPABASE_DB_URL='postgresql://user:pass@host:port/db'
.\scripts\run_migrations.ps1
```

If you store your hosted connection info in `.env`, use:

```powershell
.\scripts\run_migrations_env.ps1
```

Or run via npm:

```powershell
npm run migrate:hosted:ps1
```

You can also use the Supabase CLI if installed and configured:

```bash
npx supabase db push
```

## Access control and keys
- Use the `anon` key in frontend or untrusted contexts with RLS (Row Level Security) enabled.
- Use the `service_role` key only on backend servers; store it securely and restrict access.
- Invite team members via the Supabase dashboard and assign appropriate roles.

## Using Supabase from Python (example)
Install the Python client:

```bash
pip install supabase
```

Example usage:

```python
from supabase import create_client
import os

url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
supabase = create_client(url, key)

# Insert example
data = {"symbol": "EURUSD", "size": 0.1, "direction": "buy"}
supabase.table('trades').insert(data).execute()

# Select example
resp = supabase.table('trades').select('*').limit(10).execute()
print(resp.data)
```

## CI / Deployment
- Store `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_DB_URL` as secrets in your CI/CD provider.
- Use these secrets to run migrations and start backend services.

## Team guidelines (use this as policy)
- All new persistent data must be stored in Supabase.
- Use RLS and row-level policies for any user-scoped data.
- Service keys must never be stored in the repo.
- Share project access via the Supabase dashboard; do not share raw keys in chat.

## Helpful commands

```bash
# Hosted Supabase: apply migrations to the remote database
SUPABASE_DB_URL='postgresql://user:pass@host:port/db' ./scripts/run_migrations.sh

# or, if using PowerShell:
$env:SUPABASE_DB_URL='postgresql://user:pass@host:port/db'
.\scripts\run_migrations.ps1

# Use the Supabase CLI to push schema when configured
npx supabase db push

# Local Docker development only
supabase start
supabase stop
```

## Next steps for our repo
- Add your `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_DB_URL` to a local `.env` (not committed).
- Use the `supabase` client in backend services for DB access.
- Follow the `db/migrations` pattern for any schema changes.

If you want, I can:
- add a `db/migrations/` starter folder and example migration
- add a short PR template reminding developers to avoid committing keys

---
Created for this repo to standardize use of Supabase as the project database.
