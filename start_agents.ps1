# ============================================================
#  Autonomous Agents Launcher  (persistent / detached)
#
#  Launches Guardian, Coach, Supervisor, Scout, Telegram-HQ as
#  INDEPENDENT hidden processes that SURVIVE this window closing.
#
#  PER-AGENT idempotent: launches ONLY the agents not already
#  running (never duplicates). Stop with stop_agents.ps1.
# ============================================================

$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $root "logs\agents"
New-Item -ItemType Directory -Force $logDir | Out-Null
$pidFile = Join-Path $root "logs\_agent_pids.json"

$agents = @(
  @{ name = "ea_guardian"; args = @("-m","trading_agents.ea_agents.ea_guardian") },
  @{ name = "ea_coach";    args = @("-m","trading_agents.ea_agents.ea_coach","--loop") },
  @{ name = "supervisor";  args = @("-m","trading_agents.supervisor_agent","--interval","10") },
  @{ name = "scout";       args = @("-m","trading_agents.strategy_scout.growth_pipeline","--interval","8") },
  @{ name = "telegram_hq"; args = @("-m","trading_agents.telegram_hq_digest") }
)

# Load existing pid map (so we only start what's missing — no duplicates)
$pids = @{}
if (Test-Path $pidFile) {
  try {
    (Get-Content $pidFile -Raw | ConvertFrom-Json).PSObject.Properties |
      ForEach-Object { $pids[$_.Name] = [int]$_.Value }
  } catch { }
}

foreach ($a in $agents) {
  $n = $a.name
  $alive = $pids.ContainsKey($n) -and (Get-Process -Id $pids[$n] -ErrorAction SilentlyContinue)
  if ($alive) {
    Write-Host "[INFO] $n already running (PID $($pids[$n])) - skip" -ForegroundColor DarkGray
    continue
  }
  $out = Join-Path $logDir "$n.log"
  $err = Join-Path $logDir "$n.err.log"
  $p = Start-Process -FilePath "python" -ArgumentList $a.args `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
  $pids[$n] = $p.Id
  Write-Host "[INFO] Started $n (PID $($p.Id))  ->  $out" -ForegroundColor Green
}

$pids | ConvertTo-Json | Set-Content -Encoding utf8 $pidFile
Write-Host "[INFO] Agents persistent. PIDs: $pidFile  |  Stop: stop_agents.ps1" -ForegroundColor Cyan
