# Undo scripts\demote_local.ps1 — restore this PC's live autostarts.
# Re-enables the scheduled tasks and moves the Startup-folder items back.
#
#   powershell -ExecutionPolicy Bypass -File scripts\promote_local.ps1

$ErrorActionPreference = "Continue"
$backup  = "C:\Users\Junait\mt5 bot\autostart\_demoted_local_backup"
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"

Write-Host "== Restoring LOCAL autostarts ==" -ForegroundColor Cyan

foreach ($f in @("MT5Bot_Startup.vbs", "TradingView_CDP.vbs")) {
    if (Test-Path "$backup\$f") {
        Move-Item "$backup\$f" "$startup\$f" -Force
        Write-Host "[restored] Startup\$f" -ForegroundColor Green
    }
}

foreach ($t in @("JTCC_Watchdog", "MTF_Live_Trader", "MTF_Start_MT5",
                 "Hermes_Gateway", "START_LIVE_TRADER")) {
    try {
        Enable-ScheduledTask -TaskName $t -ErrorAction Stop | Out-Null
        Write-Host "[enabled]  task $t" -ForegroundColor Green
    } catch { Write-Host "[skip]     task $t (not found)" }
}

$envFile = "C:\Users\Junait\mt5 bot\.env"
if (Test-Path $envFile) {
    $c = Get-Content $envFile -Raw
    $c = [regex]::Replace($c, "(?m)^DEPLOYMENT_MODE=.*$", "DEPLOYMENT_MODE=vps")
    Set-Content -Path $envFile -Value $c -Encoding UTF8
    Write-Host "[env]      DEPLOYMENT_MODE=vps" -ForegroundColor Green
}
Write-Host "`n== Local restored. Reboot or re-run autostarts to resume. ==" -ForegroundColor Cyan
