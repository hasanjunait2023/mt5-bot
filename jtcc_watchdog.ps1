# =============================================================
# JTCC Watchdog - keeps the bridge + JTCC stack alive.
# Modes:
#   .\jtcc_watchdog.ps1          single check
#   .\jtcc_watchdog.ps1 -Loop    persistent loop (checks every IntervalSec)
# Restarts only dead components (idempotent). Logs to logs/jtcc/watchdog.log
# ASCII-only (PowerShell 5.1 reads .ps1 as ANSI; Unicode breaks the parser).
# =============================================================

param([switch]$Loop, [int]$IntervalSec = 300)

$ErrorActionPreference = "Continue"
$ProjectDir = "C:\Users\Junait\mt5 bot"
Set-Location $ProjectDir

$LogDir = "$ProjectDir\logs\jtcc"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
$WatchdogLog = "$LogDir\watchdog.log"

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $WatchdogLog -Value "$ts  $Msg"
}

function Test-ProcessAlive {
    param([string]$Pattern)
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Pattern*" }
    return ($procs -and @($procs).Count -ge 1)
}

function Invoke-WatchdogCheck {
    Write-Log "=== check start ==="

    # 1. MT5 terminal must be running (bridge depends on it). Relaunch if dead -
    #    terminal auto-logs into the last account, so the bridge reconnects on its
    #    next _ensure_mt5() once it's back up.
    $mt5 = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
    if (-not $mt5) {
        $mt5Exe = if ($env:MT5_TERMINAL_PATH) { $env:MT5_TERMINAL_PATH } `
                  else { "C:\Program Files\MetaTrader 5\terminal64.exe" }
        if (Test-Path $mt5Exe) {
            Write-Log "MT5 terminal64.exe DOWN - relaunching: $mt5Exe"
            Start-Process -FilePath $mt5Exe
            Start-Sleep -Seconds 20   # let it boot + auto-login before bridge reconnect
            Write-Log "MT5 terminal relaunch issued."
        } else {
            Write-Log "WARNING: terminal64.exe NOT running and exe missing at $mt5Exe - cannot relaunch."
        }
    } else {
        Write-Log "MT5 terminal OK."
    }

    # 2. MT5 FastAPI bridge (port 8090) - retry 3x before declaring down
    # (avoids false-positive restarts on transient load timeouts)
    $bridgeAlive = $false
    for ($try = 1; $try -le 3; $try++) {
        try {
            $resp = Invoke-RestMethod -Uri "http://localhost:8090/health" -TimeoutSec 8 -ErrorAction Stop
            if ($resp.status -eq "ok") { $bridgeAlive = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    }

    if (-not $bridgeAlive) {
        Write-Log "Bridge DOWN - restarting..."
        & "$ProjectDir\start_mt5_bridge.ps1" -Port 8090 -Force | Out-Null
        Start-Sleep -Seconds 8
        Write-Log "Bridge restart issued."
    } else {
        Write-Log "Bridge OK."
    }

    # 3. JTCC stack components
    $components = @{
        "jtcc_main"     = "trading_agents.jtcc.main"
        "jtcc_guardian" = "trading_agents.jtcc.guardian"
        "jtcc_coach"    = "trading_agents.jtcc.coach"
        "jtcc_digest"   = "trading_agents.jtcc.digest"
    }

    $anyDead = $false
    foreach ($name in $components.Keys) {
        if (-not (Test-ProcessAlive -Pattern $components[$name])) {
            Write-Log "$name DOWN."
            $anyDead = $true
        }
    }

    if ($anyDead) {
        Write-Log "Restarting JTCC stack (idempotent)..."
        & "$ProjectDir\start_jtcc_agents.ps1" | Out-Null
        Write-Log "JTCC stack restart issued."
    } else {
        Write-Log "All 4 JTCC components OK."
    }

    Write-Log "=== check done ==="
}

# Entry point
if ($Loop) {
    Write-Log "LOOP mode started (interval $IntervalSec s)"
    while ($true) {
        try { Invoke-WatchdogCheck } catch { Write-Log "Check error: $_" }
        Start-Sleep -Seconds $IntervalSec
    }
} else {
    Invoke-WatchdogCheck
}
