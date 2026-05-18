# ================================================================
#  MT5 Trading Bot — STOP Script
#  Usage: Right-click → Run with PowerShell
#         or: powershell -File stop_bot.ps1
# ================================================================

$PidFile = "c:\Users\Junait\mt5 bot\autostart\bot.pid"
$stopped = $false

Write-Host ""
Write-Host "Stopping MT5 Trading Bot..." -ForegroundColor Yellow

# Try PID file first
if (Test-Path $PidFile) {
    $savedPid = [int](Get-Content $PidFile -ErrorAction SilentlyContinue)
    if ($savedPid -gt 0) {
        $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $savedPid -Force
            Write-Host "[OK] Stopped bot PID $savedPid" -ForegroundColor Green
            $stopped = $true
        }
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# Fallback: find by command line
$procs = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*mtf_live_trader*" }
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Stopped trader PID $($p.ProcessId)" -ForegroundColor Green
    $stopped = $true
}

if (-not $stopped) {
    Write-Host "[INFO] No running bot found." -ForegroundColor Cyan
} else {
    # Mark state file as stopped
    $stateFile = "c:\Users\Junait\mt5 bot\mt5_bridge\_live_state.json"
    if (Test-Path $stateFile) {
        try {
            $state = Get-Content $stateFile | ConvertFrom-Json
            $state.trader_running = $false
            $state | ConvertTo-Json -Depth 10 | Out-File $stateFile -Encoding utf8
        } catch {}
    }
    Write-Host ""
    Write-Host "Bot stopped successfully." -ForegroundColor Green
}

Write-Host ""
Read-Host "Press ENTER to close"
