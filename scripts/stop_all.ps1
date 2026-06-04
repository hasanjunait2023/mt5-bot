# Stop EVERYTHING the bot runs — used for a clean cutover to the orchestrator.
# Kills: the orchestrator, the old START_*.bat restart-loop windows, and every
# managed python process. Leaves the MetaTrader 5 terminal (GUI) running.
#
#   powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1

$ErrorActionPreference = "SilentlyContinue"
Write-Host "Stopping orchestrator + all managed processes..." -ForegroundColor Yellow

# 1. Orchestrator (release its lock cleanly first)
python -m trading_agents.orchestrator stop 2>$null

# 2. Old .bat restart-loop windows (cmd.exe hosting START_*.bat)
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
    Where-Object { $_.CommandLine -match "START_(LIVE_TRADER|ICONIC_AGENT|SCALP_AGENT|DASHBOARD)\.bat" } |
    ForEach-Object { Write-Host "  kill cmd $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }

# 3. Managed python processes (match each service's command line)
$patterns = @(
    "mtf_live_trader",
    "trading_agents.iconic.agent",
    "trading_agents.scalp.agent",
    "trading_agents.jtcc.main",
    "trading_agents.jtcc.guardian",
    "trading_agents.jtcc.coach",
    "trading_agents.jtcc.digest",
    "mt5_bridge.api_server",
    "uvicorn main:app",
    "trading_agents.orchestrator"
)
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | ForEach-Object {
    $cl = $_.CommandLine
    if ($cl) {
        foreach ($p in $patterns) {
            if ($cl -like "*$p*") {
                Write-Host "  kill python $($_.ProcessId)  ($p)"
                Stop-Process -Id $_.ProcessId -Force
                break
            }
        }
    }
}

Write-Host "Done. MetaTrader 5 terminal left running." -ForegroundColor Green
