# Demote this LOCAL PC to dev/standby for the VPS-primary split.
# Stops + DISABLES every local autostart so a reboot can't run live agents,
# Telegram polling, MT5 trading, or TV CDP that would collide with the VPS
# (double orders / Telegram 409 / fighting the single TV session).
#
# Fully reversible: scheduled tasks are DISABLED (not deleted); Startup-folder
# items are MOVED to a backup folder. Run scripts/promote_local.ps1 to undo.
#
#   powershell -ExecutionPolicy Bypass -File scripts\demote_local.ps1
#
# Run this ONLY once the VPS is confirmed live (orchestrator + Telegram + MT5),
# so there is no gap and no two-machine conflict.

$ErrorActionPreference = "Continue"
$backup = "C:\Users\Junait\mt5 bot\autostart\_demoted_local_backup"
New-Item -ItemType Directory -Force -Path $backup | Out-Null

Write-Host "== Demoting LOCAL PC to dev/standby ==" -ForegroundColor Cyan

# 1. Move Startup-folder autostarts to backup (so boot doesn't relaunch them)
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
foreach ($f in @("MT5Bot_Startup.vbs", "TradingView_CDP.vbs")) {
    if (Test-Path "$startup\$f") {
        Move-Item "$startup\$f" "$backup\$f" -Force
        Write-Host "[moved]    Startup\$f -> backup" -ForegroundColor Yellow
    } else {
        Write-Host "[skip]     Startup\$f (absent)"
    }
}

# 2. Disable scheduled tasks that run live components
$tasks = @("JTCC_Watchdog", "MTF_Live_Trader", "MTF_Start_MT5",
           "Hermes_Gateway", "START_LIVE_TRADER")
foreach ($t in $tasks) {
    try {
        if (Get-ScheduledTask -TaskName $t -ErrorAction Stop) {
            Disable-ScheduledTask -TaskName $t -ErrorAction Stop | Out-Null
            Write-Host "[disabled] task $t" -ForegroundColor Yellow
        }
    } catch { Write-Host "[skip]     task $t (not found)" }
}

# 3. Kill any currently-running local live agents
$patterns = "mtf_live_trader|trading_agents\.jtcc|trading_agents\.iconic|" +
            "trading_agents\.scalp|telegram_bot|trading_agents\.orchestrator|" +
            "signal_engine|trading_agents\.tv_desk"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match $patterns } |
    ForEach-Object {
        Write-Host "[kill]     PID $($_.ProcessId)  $((($_.CommandLine) -replace '.*python(w)?\.exe','python'))" -ForegroundColor Red
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# 4. Mark this machine as local profile (orchestrator runs nothing live here)
$envFile = "C:\Users\Junait\mt5 bot\.env"
if (Test-Path $envFile) {
    $content = Get-Content $envFile -Raw
    if ($content -match "(?m)^DEPLOYMENT_MODE=") {
        $content = [regex]::Replace($content, "(?m)^DEPLOYMENT_MODE=.*$", "DEPLOYMENT_MODE=local")
    } else {
        $content = $content.TrimEnd() + "`r`nDEPLOYMENT_MODE=local`r`n"
    }
    Set-Content -Path $envFile -Value $content -Encoding UTF8
    Write-Host "[env]      DEPLOYMENT_MODE=local" -ForegroundColor Green
}

Write-Host "`n== Local demoted. Reboot-safe: no live agents, no Telegram poll, no MT5 trade. ==" -ForegroundColor Cyan
Write-Host "Undo: re-enable tasks + move backup VBS back (scripts\promote_local.ps1)."
