@echo off
title Stop MTF Live Trader
color 0C
echo Stopping MTF Live Trader...
taskkill /FI "WINDOWTITLE eq MTF EMA Live Trader" /F >NUL 2>&1
taskkill /FI "IMAGENAME eq python.exe" /FI "MEMUSAGE gt 10000" /F >NUL 2>&1
echo Done. Trader stopped.
echo.
pause
