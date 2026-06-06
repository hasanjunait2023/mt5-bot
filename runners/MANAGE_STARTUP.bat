@echo off
title MTF Bot - Startup Manager
color 0B
echo ================================================================
echo   MTF Trading Bot - Startup Manager
echo ================================================================
echo.
echo   [1] Enable auto-start on Windows login
echo   [2] Disable auto-start
echo   [3] Check status
echo   [4] Start now (manual)
echo   [5] Stop now
echo   [6] Exit
echo.
set /p choice=Choose (1-6):

if "%choice%"=="1" goto enable
if "%choice%"=="2" goto disable
if "%choice%"=="3" goto status
if "%choice%"=="4" goto startNow
if "%choice%"=="5" goto stopNow
goto end

:enable
schtasks /Change /TN "MTF_Start_MT5"   /ENABLE >NUL 2>&1
schtasks /Change /TN "MTF_Live_Trader" /ENABLE >NUL 2>&1
echo [OK] Auto-start ENABLED. Will run at next Windows login.
goto end

:disable
schtasks /Change /TN "MTF_Start_MT5"   /DISABLE >NUL 2>&1
schtasks /Change /TN "MTF_Live_Trader" /DISABLE >NUL 2>&1
echo [OK] Auto-start DISABLED.
goto end

:status
echo.
schtasks /Query /TN "MTF_Start_MT5"   /FO LIST 2>NUL | findstr /C:"Task Name" /C:"Status" /C:"Next Run"
schtasks /Query /TN "MTF_Live_Trader" /FO LIST 2>NUL | findstr /C:"Task Name" /C:"Status" /C:"Next Run"
echo.
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
if %ERRORLEVEL%==0 (echo MT5        : RUNNING) else (echo MT5        : NOT running)
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I "python.exe" >NUL
if %ERRORLEVEL%==0 (echo LiveTrader : RUNNING) else (echo LiveTrader : NOT running)
goto end

:startNow
start "" "c:\Users\Junait\mt5 bot\runners\START_LIVE_TRADER.bat"
echo Started.
goto end

:stopNow
call "c:\Users\Junait\mt5 bot\runners\STOP_LIVE_TRADER.bat"
goto end

:end
echo.
pause
