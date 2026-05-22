@echo off
title Gold Scalp Agent
color 0A

echo ================================================================
echo   Gold Scalp Agent — GS11 Opening Range + GS07 Liquidity Sweep
echo   Symbol  : XAUUSD  ^|  Timeframe: M1
echo   Paper gate: 20 trades @ PF >= 1.3 before going LIVE
echo   Risk : 1%% per trade  ^|  Daily DD limit: 5.0%%
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
echo MT5 detected. Starting Scalp Agent in 10 seconds...
timeout /t 10 /nobreak >NUL
echo.

:restart_loop
echo [%date% %time%] Starting Gold Scalp Agent...
cd /d "c:\Users\Junait\mt5 bot"
python -m trading_agents.scalp.agent --risk 1.0 --dd 5.0

echo.
echo [%date% %time%] Agent stopped. Restarting in 15 seconds... (Ctrl+C to cancel)
timeout /t 15 /nobreak >NUL
goto restart_loop
