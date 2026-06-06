# ============================================================
#  MT5 Trading Bot - Live Trader Launcher
#  Usage: Right-click -> "Run with PowerShell"
#         or: powershell -File runners\start_bot.ps1
#
#  REQUIREMENTS:
#   1. MetaTrader5 terminal must be open and logged in
#   2. pip install -r requirements.txt  (run once)
# ============================================================

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = if ($scriptDir -like "*\runners") { Split-Path -Parent $scriptDir } else { $scriptDir }
Set-Location $ProjectRoot

# Idempotency guard: true if a python process whose command line contains
# $needle is already running (prevents duplicate traders / double-trading).
function Test-PyRunning([string]$needle) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -and $p.CommandLine -match $needle) { return $true }
    }
    return $false
}

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   MTF EMA Alignment Scalper - LIVE TRADER" -ForegroundColor Cyan
Write-Host "   Risk: 1pct equity/trade | RR 1:2 | Compound" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# Check MT5 terminal is running
$mt5 = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
if (-not $mt5) {
    $mt5 = Get-Process -Name "terminal" -ErrorAction SilentlyContinue
}
if (-not $mt5) {
    Write-Host "[WARNING] MetaTrader5 terminal not detected." -ForegroundColor Yellow
    Write-Host "          Please open MT5 and login before continuing." -ForegroundColor Yellow
    Write-Host ""
    $continue = Read-Host "Press ENTER to continue anyway, or Ctrl+C to cancel"
}

Write-Host "[INFO] Starting live trader..." -ForegroundColor Green
Write-Host "[INFO] Risk 1pct/trade | RR 1:2 | DailyDD 3pct | MaxDD 20pct" -ForegroundColor White
Write-Host ""

# Launch autonomous agents as persistent detached processes (per-agent
# idempotent - start_agents.ps1 only launches the ones not already running).
Write-Host "[INFO] Launching autonomous agents (persistent)..." -ForegroundColor Cyan
& "$scriptDir\start_agents.ps1"
Write-Host ""

# Unified CPP-FX runner (detached): EURUSD/GBPUSD/USDJPY, hybrid agent,
# HARD 20pct account-wide daily-DD breaker. Gold/Silver stay on the
# S1/S15/S18 EAs attached in MT5.
if (Test-PyRunning 'cpp_live_trader') {
    Write-Host "[INFO] CPP-FX runner already running - skip (no duplicate)." -ForegroundColor DarkGray
} else {
    Write-Host "[INFO] Launching CPP-FX unified runner (detached, 20pct daily DD)..." -ForegroundColor Cyan
    Start-Process -FilePath "python" `
        -ArgumentList "cpp_live_trader.py","--pairs","EURUSD","GBPUSD","USDJPY","--dd","20","--agent","veto","--risk","1.0" `
        -WorkingDirectory "$ProjectRoot\mt5_bridge" -WindowStyle Hidden
}
Write-Host ""

# Start the MTF live trader (skip if one is already running - no duplicate).
Set-Location "$ProjectRoot\mt5_bridge"

if (Test-PyRunning 'mtf_live_trader') {
    Write-Host "[INFO] Live trader already running - NOT starting a duplicate." -ForegroundColor Yellow
    Write-Host "[INFO] Stop the existing one first if you want a fresh start." -ForegroundColor White
} else {
    python mtf_live_trader.py `
        --risk 1.0 `
        --dd 3.0 `
        --maxdd 20.0 `
        --maxtd 6
}

Write-Host ""
Write-Host "[INFO] Live trader stopped (or was already running)." -ForegroundColor Yellow
Write-Host "[INFO] Autonomous agents keep running in the background (by design)." -ForegroundColor Cyan
Write-Host "[INFO] To stop them: run  .\runners\stop_agents.ps1" -ForegroundColor White
Read-Host "Press ENTER to exit"
