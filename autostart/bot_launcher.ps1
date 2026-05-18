# ================================================================
#  MT5 Trading Bot — Silent Background Launcher
#  Triggered at Windows login via Startup folder + Registry key.
#
#  Sequence:
#    1. Start MetaTrader 5 (hidden/minimized)
#    2. Wait for MT5 to fully load and login
#    3. Start the trading bot (fully hidden, no window)
# ================================================================

$MT5Exe    = "C:\Program Files\MetaTrader 5\terminal64.exe"
$BotDir    = "c:\Users\Junait\mt5 bot\mt5_bridge"
$PidFile   = "c:\Users\Junait\mt5 bot\autostart\bot.pid"
$LogFile   = "c:\Users\Junait\mt5 bot\autostart\launcher.log"
$Python    = (Get-Command python -ErrorAction SilentlyContinue).Source

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

Write-Log "================================================"
Write-Log "=== MT5 Bot Launcher Started ==="
Write-Log "================================================"

# ── Step 1: Start MetaTrader 5 if not already running ────────────
$mt5Running = Get-Process -Name "terminal64","terminal" -ErrorAction SilentlyContinue
if ($mt5Running) {
    Write-Log "MT5 already running (PID $($mt5Running[0].Id)) — skipping launch."
} else {
    if (Test-Path $MT5Exe) {
        Write-Log "Starting MetaTrader 5..."
        Start-Process -FilePath $MT5Exe -WindowStyle Minimized
        Write-Log "MT5 launched (minimized)."
    } else {
        Write-Log "ERROR: MT5 not found at $MT5Exe"
        exit 1
    }
}

# ── Step 2: Wait for MT5 to fully load and connect ───────────────
Write-Log "Waiting for MT5 to fully load (up to 3 minutes)..."
$elapsed = 0
$maxWait = 180

while ($elapsed -lt $maxWait) {
    $mt5 = Get-Process -Name "terminal64","terminal" -ErrorAction SilentlyContinue
    if ($mt5) {
        # Extra wait to ensure MT5 has connected to broker
        Write-Log "MT5 process detected. Waiting 45 seconds for broker connection..."
        Start-Sleep -Seconds 45
        break
    }
    Start-Sleep -Seconds 10
    $elapsed += 10
    Write-Log "Still waiting for MT5... ($elapsed/$maxWait sec)"
}

if ($elapsed -ge $maxWait) {
    Write-Log "WARNING: MT5 did not start in time. Attempting bot launch anyway..."
}

# ── Step 3: Kill any existing bot instances ───────────────────────
$existing = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*mtf_live_trader*" }
foreach ($p in $existing) {
    Write-Log "Killing stale bot instance PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# ── Step 4: Launch trading bot hidden ────────────────────────────
Write-Log "Launching trading bot (background, no window)..."

if (-not $Python) {
    Write-Log "ERROR: Python not found in PATH."
    exit 1
}

$proc = Start-Process `
    -FilePath $Python `
    -ArgumentList "mtf_live_trader.py --risk 1.0 --dd 3.0 --maxdd 20.0 --maxtd 6" `
    -WorkingDirectory $BotDir `
    -WindowStyle Hidden `
    -PassThru

if ($proc -and $proc.Id) {
    $proc.Id | Out-File -FilePath $PidFile -Encoding utf8 -Force
    Write-Log "Bot started successfully — PID $($proc.Id)"
    Write-Log "Live log: $BotDir\_live_log.txt"
} else {
    Write-Log "ERROR: Bot process failed to start."
}

# ── Step 5: Launch Strategy 6 — Asian Range Breakout Bot ─────────
Write-Log "Launching Strategy 6 — Asian Range Breakout Bot..."

$s6Proc = Start-Process `
    -FilePath $Python `
    -ArgumentList "mt5_bridge/strategy6_asian_range.py" `
    -WorkingDirectory "c:\Users\Junait\mt5 bot" `
    -WindowStyle Hidden `
    -PassThru

if ($s6Proc -and $s6Proc.Id) {
    Write-Log "Strategy 6 started — PID $($s6Proc.Id)"
} else {
    Write-Log "ERROR: Strategy 6 failed to start."
}

# ── Step 6 (was 5+): Launch Strategy 3 — M1 HFT Sniper ──────────
Write-Log "Launching Strategy 3 — M1 HFT Sniper..."

$s3Proc = Start-Process `
    -FilePath $Python `
    -ArgumentList "mt5_bridge/strategy3_m1_hft.py" `
    -WorkingDirectory "c:\Users\Junait\mt5 bot" `
    -WindowStyle Hidden `
    -PassThru

if ($s3Proc -and $s3Proc.Id) {
    Write-Log "Strategy 3 started — PID $($s3Proc.Id)"
} else {
    Write-Log "ERROR: Strategy 3 failed to start."
}

# ── Step 7: Launch Strategy 2 — M5 Medium Frequency Scalp ────────
Write-Log "Launching Strategy 2 — M5 Medium Frequency Scalp..."

$s2Proc = Start-Process `
    -FilePath $Python `
    -ArgumentList "mt5_bridge/strategy2_m5_scalp.py" `
    -WorkingDirectory "c:\Users\Junait\mt5 bot" `
    -WindowStyle Hidden `
    -PassThru

if ($s2Proc -and $s2Proc.Id) {
    Write-Log "Strategy 2 started — PID $($s2Proc.Id)"
} else {
    Write-Log "ERROR: Strategy 2 failed to start."
}

# ── Step 8: Launch Strategy 1 — Swing Scalp ──────────────────────
Write-Log "Launching Strategy 1 — Low Frequency Swing Scalp..."

$s1Proc = Start-Process `
    -FilePath $Python `
    -ArgumentList "mt5_bridge/strategy1_swing_scalp.py" `
    -WorkingDirectory "c:\Users\Junait\mt5 bot" `
    -WindowStyle Hidden `
    -PassThru

if ($s1Proc -and $s1Proc.Id) {
    Write-Log "Strategy 1 started — PID $($s1Proc.Id)"
} else {
    Write-Log "ERROR: Strategy 1 failed to start."
}

# ── Step 9: Launch Strategy 4 — Multi-Pair Parallel Engine ───────
Write-Log "Launching Strategy 4 — Multi-Pair Parallel Engine..."

$s4Proc = Start-Process `
    -FilePath $Python `
    -ArgumentList "mt5_bridge/strategy4_multi_pair.py" `
    -WorkingDirectory "c:\Users\Junait\mt5 bot" `
    -WindowStyle Hidden `
    -PassThru

if ($s4Proc -and $s4Proc.Id) {
    Write-Log "Strategy 4 started — PID $($s4Proc.Id)"
} else {
    Write-Log "ERROR: Strategy 4 failed to start."
}

# ── Step 10: Launch Maic CEO Agent Telegram Bot ──────────────────
Write-Log "Launching Maic CEO Agent Telegram Bot..."

$maicProc = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList "/c `"c:\Users\Junait\mt5 bot\autostart\start_maic.bat`"" `
    -WindowStyle Hidden `
    -PassThru

if ($maicProc -and $maicProc.Id) {
    Write-Log "Maic Telegram Bot started — PID $($maicProc.Id)"
} else {
    Write-Log "ERROR: Maic Telegram Bot failed to start."
}

Write-Log "=== Launcher finished ==="
