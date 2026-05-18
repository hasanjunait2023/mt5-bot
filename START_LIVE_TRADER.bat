@echo off
title MTF EMA Live Trader
color 0A

echo ================================================================
echo   MTF EMA Alignment Scalper - LIVE TRADER  v2 (optimized)
echo   Tier1: CADJPY EURJPY USDJPY GBPAUD BTCUSD AUDNZD
echo          USDCAD EURUSD AUDCHF NZDUSD
echo   New  : EURNZD NZDJPY AUDCAD GBPJPY AUDUSD AUDJPY
echo          GBPUSD XAUUSD
echo   Risk : 2%% per trade  ^|  Daily DD limit: 4.5%%
echo ================================================================
echo.

:: Wait for MT5 to be running (check every 5s, max 3 minutes)
echo Waiting for MetaTrader 5 to start...
set /a tries=0
:wait_mt5
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
if %ERRORLEVEL%==0 goto mt5_ready
set /a tries=%tries%+1
if %tries% GEQ 36 (
    echo MT5 not detected after 3 minutes - starting trader anyway...
    goto mt5_ready
)
timeout /t 5 /nobreak >NUL
goto wait_mt5

:mt5_ready
echo MT5 detected. Starting live trader in 10 seconds...
timeout /t 10 /nobreak >NUL
echo.

:: Auto-restart loop — if trader crashes, restart after 15 seconds
:restart_loop
echo [%date% %time%] Starting MTF Live Trader...
cd /d "c:\Users\Junait\mt5 bot"
python mt5_bridge/mtf_live_trader.py --pairs CADJPY EURJPY USDJPY GBPAUD BTCUSD AUDNZD USDCAD EURUSD AUDCHF NZDUSD EURNZD NZDJPY AUDCAD GBPJPY AUDUSD AUDJPY GBPUSD XAUUSD --risk 2.0

echo.
echo [%date% %time%] Trader stopped. Restarting in 15 seconds... (Ctrl+C to cancel)
timeout /t 15 /nobreak >NUL
goto restart_loop
