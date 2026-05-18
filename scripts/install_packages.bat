@echo off
echo Installing Python packages for ScalpMaster HFT MT5 Bridge...
"C:\Users\Junait\AppData\Local\Programs\Python\Python312\python.exe" -m pip install MetaTrader5 pandas numpy matplotlib
echo.
echo Done! Exit code: %ERRORLEVEL%
pause
