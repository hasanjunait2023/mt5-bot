@echo off
REM ============================================================================
REM Auto-publish — every 4h, headless Claude runs the /auto-publish workflow
REM (detect pending work -> gate: ruff+pytest+build -> bounded auto-fix -> push
REM to master, or stay silent/alert). Triggered by Task Scheduler "MT5_AutoPublish".
REM Safety lives in .claude/commands/auto-publish.md (never pushes red/secret/WIP).
REM ============================================================================
cd /d "c:\Users\Junait\mt5 bot"
if not exist logs mkdir logs
echo [%date% %time%] === auto-publish start === >> logs\auto_publish.log
"C:\Users\Junait\.local\bin\claude.exe" -p "/auto-publish" --dangerously-skip-permissions >> logs\auto_publish.log 2>&1
echo [%date% %time%] === auto-publish end === >> logs\auto_publish.log
