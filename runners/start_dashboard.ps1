# ============================================================
#  MT5 Trading Bot — Dashboard Launcher
#  Starts the FastAPI backend + opens browser for frontend
#  Usage: powershell -File runners\start_dashboard.ps1
# ============================================================

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = if ($scriptDir -like "*\runners") { Split-Path -Parent $scriptDir } else { $scriptDir }
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   Trading Dashboard — Starting..." -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# Start backend API in background. Backend uses local imports (core.config, api.*)
# so uvicorn must be launched from inside dashboard/backend/, not the project root.
Write-Host "[INFO] Starting FastAPI backend on http://localhost:8000" -ForegroundColor Green
$backendDir = Join-Path $ProjectRoot "dashboard\backend"
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:backendDir
    python -m uvicorn main:app --host 0.0.0.0 --port 8000
}

Start-Sleep -Seconds 3

# Check if frontend exists
$frontendPath = "$ProjectRoot\dashboard\frontend"
if (Test-Path "$frontendPath\package.json") {
    Write-Host "[INFO] Starting Vite frontend on http://localhost:5173" -ForegroundColor Green
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$frontendPath'; npm run dev"
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
