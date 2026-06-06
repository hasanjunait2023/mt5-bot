# ============================================================
#  CPP — Confluence Pullback Portfolio (unified) launcher
#  CPP-FX (EURUSD/GBPUSD/USDJPY) via cpp_live_trader.py with the
#  hybrid confirmation agent + HARD 6% account-wide daily-DD breaker.
#  Gold/Silver keep running on S1/S15/S18 EAs attached in MT5.
#  Usage:  powershell -File runners\start_cpp.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = if ($scriptDir -like "*\runners") { Split-Path -Parent $scriptDir } else { $scriptDir }
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   CPP — Confluence Pullback Portfolio (FX)" -ForegroundColor Cyan
Write-Host "   EURUSD GBPUSD USDJPY | Risk 1% | RR 1:2" -ForegroundColor Green
Write-Host "   Agent: veto | HARD daily DD breaker: 20%" -ForegroundColor Green
Write-Host "   Gold/Silver -> S1/S15/S18 EAs (attach in MT5)" -ForegroundColor White
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

$mt5 = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
if (-not $mt5) { $mt5 = Get-Process -Name "terminal" -ErrorAction SilentlyContinue }
if (-not $mt5) {
    Write-Host "[WARNING] MetaTrader5 terminal not detected. Open + login first." -ForegroundColor Yellow
    Read-Host "Press ENTER to continue anyway, or Ctrl+C to cancel"
}

Set-Location "$ProjectRoot\mt5_bridge"
python cpp_live_trader.py --pairs EURUSD GBPUSD USDJPY --dd 20 --agent veto --risk 1.0

Write-Host ""
Write-Host "[INFO] CPP runner stopped." -ForegroundColor Yellow
Read-Host "Press ENTER to exit"
