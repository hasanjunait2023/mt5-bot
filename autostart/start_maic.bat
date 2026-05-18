@echo off
cd /d "c:\Users\Junait\mt5 bot"
:loop
python telegram_bot.py >> "c:\Users\Junait\mt5 bot\logs\maic_bot.log" 2>&1
echo [%date% %time%] Bot exited, restarting in 5s... >> "c:\Users\Junait\mt5 bot\logs\maic_bot.log"
timeout /t 5 /nobreak >nul
goto loop
