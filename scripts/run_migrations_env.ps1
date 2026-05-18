$envFile = Join-Path $PSScriptRoot '..\.env'
if (-not (Test-Path $envFile)) {
  Write-Error ".env file not found. Copy .env.example to .env and fill in your Supabase values."
  exit 1
}

Get-Content $envFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#')) { return }
  $parts = $line -split('=', 2)
  if ($parts.Count -eq 2) {
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    $env:$name = $value
  }
}

if (-not $env:SUPABASE_DB_URL) {
  Write-Error "Error: SUPABASE_DB_URL is not set in .env."
  exit 1
}

$files = Get-ChildItem -Path (Join-Path $PSScriptRoot '..\db\migrations') -Filter *.sql -ErrorAction SilentlyContinue
if (-not $files) {
  Write-Output "No migrations found in db/migrations."
  exit 0
}

foreach ($f in $files) {
  Write-Output "Applying migration: $($f.FullName)"
  psql $env:SUPABASE_DB_URL -v ON_ERROR_STOP=1 -f $f.FullName
}

Write-Output "All migrations applied."
