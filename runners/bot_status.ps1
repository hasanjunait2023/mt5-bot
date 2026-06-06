# ================================================================
#  MT5 Trading Bot — Status Check
#  Shows whether bot is running and last log entries.
# ================================================================

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = if ($scriptDir -like "*\runners") { Split-Path -Parent $scriptDir } else { $scriptDir }

$PidFile   = "$ProjectRoot\autostart\bot.pid"
$LogFile   = "$ProjectRoot\mt5_bridge\_live_log.txt"
$StateFile = "$ProjectRoot\mt5_bridge\_live_state.json"

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "   MT5 Trading Bot — Status" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# ── Process check ─────────────────────────────────────────────────
$procs = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*mtf_live_trader*" }
if ($procs) {
    Write-Host "Bot Process : RUNNING" -ForegroundColor Green
    foreach ($p in $procs) {
        Write-Host "             PID $($p.ProcessId)" -ForegroundColor Green
    }
} else {
    Write-Host "Bot Process : STOPPED" -ForegroundColor Red
}

# ── Account info from state file ──────────────────────────────────
if (Test-Path $StateFile) {
    try {
        $state = Get-Content $StateFile | ConvertFrom-Json
        $acc   = $state.account
        $ts    = $state.timestamp

        Write-Host ""
        Write-Host "Last Update : $ts"
        Write-Host "Account     : #$($acc.login) @ $($acc.server)"
        Write-Host "Balance     : `$$($acc.balance)"
        Write-Host "Equity      : `$$($acc.equity)"
        Write-Host "Daily PnL   : `$$($acc.daily_pnl)"
        Write-Host "Daily DD    : $($acc.daily_dd_pct)%"
        Write-Host "Total DD    : $($acc.total_dd_pct)%"

        $positions = $state.positions
        Write-Host ""
        if ($positions -and $positions.Count -gt 0) {
            Write-Host "Open Positions ($($positions.Count)):" -ForegroundColor Yellow
            foreach ($p in $positions) {
                Write-Host "  $($p.symbol) $($p.direction) $($p.volume)L  Entry=$($p.entry_price)  P&L=`$$($p.profit)"
            }
        } else {
            Write-Host "Open Positions : None"
        }

        $trades = $state.daily_trades
        if ($trades) {
            Write-Host ""
            Write-Host "Trades Today:"
            $trades.PSObject.Properties | ForEach-Object {
                Write-Host "  $($_.Name): $($_.Value) trade(s)"
            }
        }
    } catch {
        Write-Host "Could not read state file." -ForegroundColor Yellow
    }
}

# ── Last 5 log lines ──────────────────────────────────────────────
Write-Host ""
Write-Host "Last Log Entries:" -ForegroundColor Cyan
if (Test-Path $LogFile) {
    Get-Content $LogFile -Tail 6 | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "  Log file not found."
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Press ENTER to close"
