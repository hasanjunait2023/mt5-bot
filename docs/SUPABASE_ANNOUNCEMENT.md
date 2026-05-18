# Supabase Adoption Announcement

Team,

We standardised on Supabase for the project database. See the full setup and usage guide: [SUPABASE_SETUP.md](SUPABASE_SETUP.md).

Action items for each developer:

- Request access to the Supabase project from the repo owner (do not share keys in chat).
- Add the following env vars to your local `.env` (do not commit):
  - `SUPABASE_URL`
  - `SUPABASE_ANON_KEY`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_DB_URL`
- Use Hosted Supabase for local development by running your app against the remote project.
- Docker and `supabase start` are only needed if you want a local Supabase stack.
- Use the `supabase` Python client or server SDKs in backend services (examples in `SUPABASE_SETUP.md`).

Notes:
- The `service_role` key is sensitive — only use it on trusted backend services and CI. Never commit keys to Git.
- Use Row Level Security (RLS) for user-scoped data when calling Supabase from frontends.

If you need access, reply here and include your email. I'll add you to the Supabase project and confirm roles.
