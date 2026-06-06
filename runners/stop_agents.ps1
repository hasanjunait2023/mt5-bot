# Stop the detached autonomous agents started by start_agents.ps1.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = if ($scriptDir -like "*\runners") { Split-Path -Parent $scriptDir } else { $scriptDir }
$pidFile = Join-Path $root "logs\_agent_pids.json"

if (-not (Test-Path $pidFile)) {
  Write-Host "[INFO] No pidfile - agents not tracked / not running." -ForegroundColor Yellow
  return
}

$pids = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($prop in $pids.PSObject.Properties) {
  $proc = Get-Process -Id $prop.Value -ErrorAction SilentlyContinue
  if ($proc) {
    Stop-Process -Id $prop.Value -Force
    Write-Host "[INFO] Stopped $($prop.Name) (PID $($prop.Value))" -ForegroundColor Yellow
  } else {
    Write-Host "[INFO] $($prop.Name) (PID $($prop.Value)) already gone" -ForegroundColor DarkGray
  }
}
Remove-Item $pidFile -Force
Write-Host "[INFO] All agents stopped." -ForegroundColor Green
