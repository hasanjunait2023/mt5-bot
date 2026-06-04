# ui_designer_run.ps1 - headless run of the dashboard-designer agent.
# Invoked by the "MT5 Dashboard Designer" scheduled task (twice daily).
# Makes ONE premium-UI improvement to the dashboard frontend, build-gates it,
# verifies, deploys to the VPS (:8010), commits, pushes, and logs.
#
# Guards (learned from the first run):
#  - single-instance lock (never overlap)
#  - DIRTY-TREE GUARD: refuse to run if the tree already has uncommitted changes,
#    so the agent never collides with a human/other session or sweeps their edits
#    into its commit.
#  - hard timeout so a hung verify/login step cannot run for an hour.
#  - real stdout/stderr capture into the per-run log.
#
# ASCII-ONLY on purpose: Windows PowerShell 5.1 reads non-BOM UTF-8 as cp1252,
# which corrupts any fancy dashes/box chars and breaks parsing. Keep it plain.
#
# Manual run:  powershell -File scripts\ui_designer_run.ps1

$ErrorActionPreference = 'Continue'
$Repo   = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Repo 'logs\ui_designer'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log   = Join-Path $LogDir "run-$Stamp.log"
$Lock  = Join-Path $LogDir '.lock'
$TimeoutMin = 25

function Log($m) { "$([DateTime]::UtcNow.ToString('o'))  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

"=== dashboard-designer run $Stamp ===" | Out-File -FilePath $Log -Encoding utf8

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
  Set-Location $Repo

  # start from latest master (best effort)
  git pull --ff-only origin master 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8

  # DIRTY-TREE GUARD (ignore untracked build output; only care about tracked edits)
  $dirty = git status --porcelain --untracked-files=no
  if ($dirty) {
    Log "SKIPPED: working tree dirty (uncommitted tracked changes) - not safe to auto-edit:"
    $dirty | Out-File -FilePath $Log -Append -Encoding utf8
    exit 0
  }

  $claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
  if (-not $claude) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
  Log "repo=$Repo claude=$claude timeout=${TimeoutMin}m"

  $Prompt = 'Run ONE dashboard UI improvement cycle now by reading and strictly following .claude/skills/dashboard-designer/SKILL.md. Obey every guardrail: scope is dashboard/frontend only; ONE focused improvement; build-gate with `npx vite build`; visual verify is BEST-EFFORT and time-boxed (if the browser/login does not respond within ~3 minutes, skip it and rely on the build-gate plus post-deploy curl - do NOT block); stage and commit ONLY the specific files you edited (never git add whole directories); deploy to the VPS :8010; push; append to dashboard/UI_POLISH_LOG.md. If nothing is high-value or a gate fails twice, revert and log "skipped". Never touch trading/backend code. Finish within 20 minutes.'

  $claudeArgs = @('-p', $Prompt, '--dangerously-skip-permissions')
  $proc = Start-Process -FilePath $claude -ArgumentList $claudeArgs -WorkingDirectory $Repo `
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
