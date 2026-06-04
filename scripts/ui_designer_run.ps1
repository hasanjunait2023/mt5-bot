# ui_designer_run.ps1 — headless run of the dashboard-designer agent.
# Invoked by the "MT5 Dashboard Designer" scheduled task (twice daily).
# Makes ONE premium-UI improvement to the dashboard frontend, build-gates it,
# verifies, deploys to the VPS (:8010), commits, pushes, and logs.
#
# Manual run:  powershell -File scripts\ui_designer_run.ps1

$ErrorActionPreference = 'Continue'
$Repo = Split-Path -Parent $PSScriptRoot          # repo root (scripts/..)
$LogDir = Join-Path $Repo 'logs\ui_designer'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log = Join-Path $LogDir "run-$Stamp.log"

$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = "$env:USERPROFILE\.local\bin\claude" }

$Prompt = @'
Run ONE dashboard UI improvement cycle now by reading and strictly following
.claude/skills/dashboard-designer/SKILL.md. Obey every guardrail in it: scope is
dashboard/frontend only, one focused improvement, build-gate with `npx vite build`,
visually verify before/after (no regressions), deploy to the VPS :8010, then commit,
push, and append to dashboard/UI_POLISH_LOG.md. If nothing is high-value or a gate
fails twice, revert and log "skipped". Do not touch any trading/backend code.
'@

Set-Location $Repo
"=== dashboard-designer run $Stamp ===" | Out-File -FilePath $Log -Encoding utf8
"repo=$Repo claude=$claude" | Out-File -FilePath $Log -Append -Encoding utf8

# Headless, fully autonomous (self-task on the owner's box). Skill enforces scope.
& $claude -p $Prompt --dangerously-skip-permissions *>> $Log

"=== exit=$LASTEXITCODE done $(Get-Date -Format o) ===" | Out-File -FilePath $Log -Append -Encoding utf8
