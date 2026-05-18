@echo off
title MT5 Dashboard Launcher
cd /d "%~dp0"

echo.
echo  =============================================
echo   MT5 Dashboard — Starting...
echo  =============================================
echo.

REM ── Backend ──────────────────────────────────
echo  [1/3] Setting up Python backend...
cd dashboard\backend

if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo  ERROR: Could not create Python venv. Is Python installed?
        pause & exit /b 1
    )
)

.venv\Scripts\pip install -r requirements.txt -q
if errorlevel 1 (
    echo  ERROR: pip install failed.
    pause & exit /b 1
)

echo  [2/3] Starting API backend on http://localhost:8000 ...
start "MT5 Dashboard — Backend" cmd /k ".venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000"

cd ..\..

REM ── Frontend ─────────────────────────────────
echo  [3/3] Setting up React frontend...
cd dashboard\frontend

if not exist "node_modules" (
    echo  Installing npm packages...
    npm install
    if errorlevel 1 (
        echo  ERROR: npm install failed. Is Node.js installed?
        pause & exit /b 1
    )
)

echo  Starting frontend on http://localhost:5173 ...
start "MT5 Dashboard — Frontend" cmd /k "npm run dev"

cd ..\..

echo.
echo  =============================================
echo   Dashboard is starting up!
echo.
echo   Backend API:  http://localhost:8000/docs
echo   Frontend:     http://localhost:5173
echo.
echo   (May take ~5s for both to be ready)
echo  =============================================
echo.
timeout /t 5 /nobreak >nul
start http://localhost:5173
