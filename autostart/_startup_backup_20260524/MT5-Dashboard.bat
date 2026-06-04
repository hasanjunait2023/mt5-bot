@echo off
REM MT5 Dashboard — auto-start on login
REM Serves frontend + API at http://localhost:8000

cd /d "C:\Users\Junait\mt5 bot\dashboard\backend"

REM Wait 15s for network/MT5 to settle
timeout /t 15 /nobreak >nul

start "" /min "C:\Users\Junait\mt5 bot\dashboard\backend\.venv\Scripts\uvicorn.exe" main:app --host 0.0.0.0 --port 8000
