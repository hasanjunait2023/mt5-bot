# Install the orchestrator so the whole bot survives sleep, lock, and logoff.
#
# Does three things:
#   1. Stops the trading PC from sleeping on AC power (a sleeping PC = dead bot).
#   2. Registers a Scheduled Task that launches the orchestrator at logon and
#      auto-restarts it on failure, running in the user's interactive session so
#      it can drive the MetaTrader 5 GUI.
#   3. Prints how to start it now and how to check status.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1
#
# Re-run any time to update. Use -Uninstall to remove the task.

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$TaskName = "MT5Bot-Orchestrator"
$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path
$Python = (Get-Command python).Source

if ($Uninstall) {
    schtasks /Delete /TN $TaskName /F 2>$null
    Write-Host "Removed scheduled task $TaskName" -ForegroundColor Green
    return
}

# Must be elevated — Scheduled Task registration requires admin on this machine.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "This script must run as Administrator (right-click PowerShell -> Run as administrator)." -ForegroundColor Red
    Write-Host "It registers the auto-start task and disables AC sleep." -ForegroundColor Red
    return
}

# ── 1. Never sleep on AC (monitor may still turn off; machine stays awake) ──────
Write-Host "[1/3] Disabling sleep/hibernate on AC power..." -ForegroundColor Cyan
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Host "      standby-timeout-ac = 0 (never)" -ForegroundColor DarkGray

# ── 2. Register the scheduled task (via schtasks — robust, runs at logon) ────────
Write-Host "[2/3] Registering scheduled task '$TaskName'..." -ForegroundColor Cyan

# A wrapper .bat keeps schtasks from having to parse cd/redirection operators.
$wrapper = Join-Path $ProjectDir "scripts\run_orchestrator.bat"
schtasks /Create /TN $TaskName /TR "`"$wrapper`"" /SC ONLOGON /RL HIGHEST /F | Out-Null
Write-Host "      Task registered (AtLogOn, highest privileges)." -ForegroundColor DarkGray

# ── 3. Next steps ───────────────────────────────────────────────────────────────
Write-Host "[3/3] Done." -ForegroundColor Green
Write-Host ""
Write-Host "Start now (clean cutover):" -ForegroundColor Yellow
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1   # kill old launchers"
Write-Host "  Start-ScheduledTask -TaskName $TaskName                         # start orchestrator"
Write-Host ""
Write-Host "Check status:" -ForegroundColor Yellow
Write-Host "  python -m trading_agents.orchestrator status"
Write-Host "  python scripts\triage.py"
