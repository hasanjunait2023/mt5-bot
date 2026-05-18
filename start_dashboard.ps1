# ============================================================
#  MT5 Trading Bot — Dashboard Launcher
#  Starts the FastAPI backend + opens browser for frontend
#  Usage: powershell -File start_dashboard.ps1
# ============================================================

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   Trading Dashboard — Starting..." -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# Start backend API in background
Write-Host "[INFO] Starting FastAPI backend on http://localhost:8000" -ForegroundColor Green
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:scriptDir
    python -m uvicorn dashboard.backend.api:app --host 0.0.0.0 --port 8000 --reload
}

Start-Sleep -Seconds 3

# Check if frontend exists
$frontendPath = "$scriptDir\dashboard\frontend"
if (Test-Path "$frontendPath\package.json") {
    Write-Host "[INFO] Starting React frontend on http://localhost:3000" -ForegroundColor Green
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$frontendPath'; npm start"
} else {
    Write-Host "[INFO] No frontend found. Dashboard API only at http://localhost:8000/docs" -ForegroundColor Yellow
}

# Open API docs in browser
Start-Sleep -Seconds 2
Start-Process "http://localhost:8000/docs"

Write-Host ""
Write-Host "[INFO] Dashboard running. Press Ctrl+C to stop backend." -ForegroundColor Yellow
Write-Host ""

# Keep alive and stream backend output
try {
    while ($true) {
        $output = Receive-Job $backendJob
        if ($output) { Write-Host $output }
        Start-Sleep -Seconds 2
    }
} finally {
    Stop-Job $backendJob
    Remove-Job $backendJob
    Write-Host "[INFO] Dashboard stopped." -ForegroundColor Yellow
}
