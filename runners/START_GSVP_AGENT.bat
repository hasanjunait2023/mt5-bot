@echo off
title GS-VP Volume Profile Agent
color 0B

echo ================================================================
echo   GS-VP Agent — Adaptive Volume Profile (breakout-retest + VA-reversion)
echo   Symbols : GBPUSD EURUSD XAUUSD BTCUSD XAGUSD  |  Timeframe: M15
echo   Account : DEMO (real orders on demo; real-money fail-closed)
echo   Gate    : per-symbol 20 trades @ PF >= 1.3 = real-ready
echo   Risk    : 1%% per trade  |  Daily DD limit: 6.0%%
echo ================================================================
echo.

:: Wait for MT5 terminal
echo Waiting for MetaTrader 5...
set /a tries=0
:wait_mt5
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
if %ERRORLEVEL%==0 goto mt5_ready
set /a tries=%tries%+1
if %tries% GEQ 36 (
    echo MT5 not detected after 3 minutes - starting anyway...
    goto mt5_ready
)
timeout /t 5 /nobreak >NUL
goto wait_mt5

:mt5_ready
echo MT5 detected. Starting GS-VP Agent in 10 seconds...
timeout /t 10 /nobreak >NUL
echo.

:restart_loop
echo [%date% %time%] Starting GS-VP Agent...
cd /d "%~dp0.."
python -m trading_agents.scalp.gsvp_agent --symbols GBPUSD EURUSD XAUUSD BTCUSD XAGUSD --risk 1.0 --dd 6.0

echo.
echo [%date% %time%] Agent stopped. Restarting in 15 seconds... (Ctrl+C to cancel)
timeout /t 15 /nobreak >NUL
goto restart_loop
