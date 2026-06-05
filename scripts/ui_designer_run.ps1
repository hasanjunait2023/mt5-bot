# ui_designer_run.ps1 - headless run of the dashboard-designer agent.
# Invoked by the "MT5 Dashboard Designer" scheduled task (twice daily).
#
# ISOLATION: operates on a DEDICATED clone ($Work), NOT the main dev repo, so it
# never collides with your live editing sessions and its commits never get
# orphaned. Each run resets that clone to pristine origin/master, so it always
# starts clean (no dirty-tree skips). gitignored node_modules/.env/dist survive
# the reset (so vite build stays fast and .env keeps DASHBOARD_PASSWORD).
#
# Guards: single-instance lock, hard timeout, real stdout/stderr capture.
# ASCII-ONLY (Windows PowerShell 5.1 reads non-BOM UTF-8 as cp1252 and would
# mangle fancy dashes -> parse errors).
#
# Manual run:  powershell -File scripts\ui_designer_run.ps1

$ErrorActionPreference = 'Continue'
$Work   = 'C:\Users\Junait\mt5-bot-ui'                 # the agent's isolated clone
$LogDir = Join-Path $Work 'logs\ui_designer'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log   = Join-Path $LogDir "run-$Stamp.log"
$Lock  = Join-Path $LogDir '.lock'
$TimeoutMin = 25

function Log($m) { "$([DateTime]::UtcNow.ToString('o'))  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }
"=== dashboard-designer run $Stamp ===" | Out-File -FilePath $Log -Encoding utf8

if (-not (Test-Path (Join-Path $Work '.git'))) {
  Log "FATAL: isolated clone missing at $Work - run setup (git clone + npm ci) first."
  exit 1
}

# single-instance lock
if (Test-Path $Lock) {
  $pidPrev = (Get-Content $Lock -ErrorAction SilentlyContinue | Select-Object -First 1)
  if ($pidPrev -and (Get-Process -Id $pidPrev -ErrorAction SilentlyContinue)) {
    Log "another run (pid $pidPrev) active - skipping."
    exit 0
  }
}
$PID | Out-File -FilePath $Lock -Encoding ascii

try {
  Set-Location $Work

  # pristine start: discard any leftover, sync to latest origin/master.
  # safe because this clone is the agent's alone (never holds human WIP).
  # clean -fd removes untracked but NOT gitignored (node_modules/.env/dist stay).
  git fetch origin 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
  git reset --hard origin/master 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
  git clean -fd 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
  Log "clone reset to $(git rev-parse --short HEAD)"

  $claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
  if (-not $claude) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
  Log "work=$Work claude=$claude timeout=${TimeoutMin}m"

  $Prompt = 'Run ONE dashboard UI improvement cycle now by reading and strictly following .claude/skills/dashboard-designer/SKILL.md. Obey every guardrail: scope is dashboard/frontend only; ONE focused improvement; build-gate with `npx vite build`; visual verify is BEST-EFFORT and time-boxed (if the browser/login does not respond within ~3 minutes, skip it and rely on the build-gate plus post-deploy curl - do NOT block); stage and commit ONLY the specific files you edited (never git add whole directories); deploy to the VPS :8010; push; append to dashboard/UI_POLISH_LOG.md. If nothing is high-value or a gate fails twice, revert and log "skipped". Never touch trading/backend code. Finish within 20 minutes.'

  $claudeArgs = @('-p', $Prompt, '--dangerously-skip-permissions')
  $proc = Start-Process -FilePath $claude -ArgumentList $claudeArgs -WorkingDirectory $Work `
            -NoNewWindow -PassThru -RedirectStandardOutput "$Log.out" -RedirectStandardError "$Log.err"
  if (-not $proc.WaitForExit($TimeoutMin * 60 * 1000)) {
    Log "TIMEOUT after ${TimeoutMin}m - killing pid $($proc.Id) and its tree."
    taskkill /T /F /PID $proc.Id 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
  } else {
    Log "claude exit=$($proc.ExitCode)"
  }
  Get-Content "$Log.out" -ErrorAction SilentlyContinue | Out-File -FilePath $Log -Append -Encoding utf8
  Get-Content "$Log.err" -ErrorAction SilentlyContinue | Out-File -FilePath $Log -Append -Encoding utf8
  Remove-Item "$Log.out","$Log.err" -ErrorAction SilentlyContinue
}
finally {
  Remove-Item $Lock -ErrorAction SilentlyContinue
  Log "=== done $([DateTime]::UtcNow.ToString('o')) ==="
}
