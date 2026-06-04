@echo off
REM Launch wrapper for the orchestrator — used by the MT5Bot-Orchestrator
REM scheduled task so schtasks doesn't have to parse redirection operators.
cd /d "C:\Users\Junait\mt5 bot"
python -m trading_agents.orchestrator >> logs\orchestrator.log 2>&1
