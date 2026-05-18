# ============================================================
#  MT5 Trading Bot — First-Time Setup
#  Run this ONCE before starting the bot.
#  Usage: powershell -File install.ps1
# ============================================================

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   MT5 Trading Bot — Installing Dependencies" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor White
$pyVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "      [ERROR] Python not found. Install Python 3.10+ from python.org" -ForegroundColor Red
    exit 1
}
Write-Host "      Found: $pyVersion" -ForegroundColor Green

# 2. Upgrade pip
Write-Host "[2/4] Upgrading pip..." -ForegroundColor White
python -m pip install --upgrade pip --quiet

# 3. Install Python packages
Write-Host "[3/4] Installing Python packages..." -ForegroundColor White
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "      [WARNING] Some packages may have failed. Check output above." -ForegroundColor Yellow
} else {
    Write-Host "      All Python packages installed." -ForegroundColor Green
}

# 4. Frontend (optional)
Write-Host "[4/4] Checking Node.js / frontend..." -ForegroundColor White
$nodeCheck = node --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "      Node.js found: $nodeCheck" -ForegroundColor Green
    $frontendPath = "$scriptDir\dashboard\frontend"
    if (Test-Path "$frontendPath\package.json") {
        Write-Host "      Installing frontend dependencies..." -ForegroundColor White
        Set-Location $frontendPath
        npm install --silent
        Set-Location $scriptDir
        Write-Host "      Frontend ready." -ForegroundColor Green
    }
} else {
    Write-Host "      Node.js not found — dashboard frontend will not be available." -ForegroundColor Yellow
    Write-Host "      Install from: https://nodejs.org" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   Setup Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "   Next steps:" -ForegroundColor White
Write-Host "   1. Fill in .env with your API keys (optional)" -ForegroundColor White
Write-Host "   2. Open MetaTrader5 and login to your account" -ForegroundColor White
Write-Host "   3. Run: .\start_bot.ps1  to start trading" -ForegroundColor White
Write-Host "   4. Run: .\start_dashboard.ps1  to open dashboard" -ForegroundColor White
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Press ENTER to exit"
