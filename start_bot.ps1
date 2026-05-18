# ============================================================
#  MT5 Trading Bot — Live Trader Launcher
#  Usage: Right-click → "Run with PowerShell"
#         or: powershell -File start_bot.ps1
#
#  REQUIREMENTS:
#   1. MetaTrader5 terminal must be open and logged in
#   2. pip install -r requirements.txt  (run once)
# ============================================================

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   MTF EMA Alignment Scalper — LIVE TRADER" -ForegroundColor Cyan
Write-Host "   Risk: 1% equity/trade  |  RR: 1:2  |  Compound" -ForegroundColor Green
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
Write-Host "[INFO] Pairs: Top performers from backtest" -ForegroundColor White
Write-Host "[INFO] Risk : 1%% per trade (equity-based compounding)" -ForegroundColor White
Write-Host "[INFO] RR   : 1:2 minimum" -ForegroundColor White
Write-Host "[INFO] Daily DD limit: 3%%" -ForegroundColor White
Write-Host "[INFO] Max DD limit  : 20%%" -ForegroundColor White
Write-Host ""

# Navigate to mt5_bridge and start trader
Set-Location "$scriptDir\mt5_bridge"

python mtf_live_trader.py `
    --risk 1.0 `
    --dd 3.0 `
    --maxdd 20.0 `
    --maxtd 6

Write-Host ""
Write-Host "[INFO] Live trader stopped." -ForegroundColor Yellow
Read-Host "Press ENTER to exit"
