if (-not $env:SUPABASE_DB_URL) {
  Write-Error "Error: SUPABASE_DB_URL environment variable is not set.`nSet it to your Supabase Postgres connection string (e.g. postgresql://user:pass@host:port/db)"
  exit 1
}

$files = Get-ChildItem -Path db/migrations -Filter *.sql -ErrorAction SilentlyContinue
if (-not $files) {
  Write-Output "No migrations found in db/migrations."
  exit 0
}

foreach ($f in $files) {
  Write-Output "Applying migration: $($f.FullName)"
  psql $env:SUPABASE_DB_URL -v ON_ERROR_STOP=1 -f $f.FullName
}

Write-Output "All migrations applied."
