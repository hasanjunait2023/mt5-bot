# =============================================================
# JTCC — Junait Trading Command Center Launcher
# Launches JTCC main.py as background process with log capture
# Usage: .\runners\start_jtcc.ps1            # live mode (reads _live_state.json)
#        .\runners\start_jtcc.ps1 -DryRun    # dry-run: signals only, no trades
#        .\runners\start_jtcc.ps1 -Symbol XAUUSD -DryRun
# =============================================================

param(
    [switch]$DryRun,
    [string]$Symbol = "",
    [switch]$Force
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = if ($scriptDir -like "*\runners") { Split-Path -Parent $scriptDir } else { $scriptDir }
Set-Location $ProjectRoot

$LogDir = "logs\jtcc"
$PidFile = "logs\_agent_pids.json"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }

# ── Idempotency guard ─────────────────────────────────────────
$existing = Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*jtcc.main*" -or $_.MainWindowTitle -like "*jtcc*" }

if ($existing -and -not $Force) {
    Write-Host "JTCC already running (PID $($existing.Id)). Use -Force to restart." -ForegroundColor Yellow
    exit 0
}

if ($existing -and $Force) {
    Write-Host "Stopping existing JTCC (PID $($existing.Id))..." -ForegroundColor Yellow
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# ── Build arguments ───────────────────────────────────────────
$args_list = @("-m", "trading_agents.jtcc.main")
if ($DryRun) { $args_list += "--dry-run" }
if ($Symbol) { $args_list += @("--symbol", $Symbol) }

$mode = if ($DryRun) { "DRY RUN" } else { "LIVE" }
$symLabel = if ($Symbol) { $Symbol } else { "all symbols" }

# ── Banner ────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   JTCC — Junait Trading Command Center               ║" -ForegroundColor Cyan
Write-Host "║   Mode: $mode | Symbols: $symLabel" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Launch ────────────────────────────────────────────────────
$logFile = "$LogDir\jtcc.log"
$errFile = "$LogDir\jtcc.err.log"

$proc = Start-Process python `
    -ArgumentList $args_list `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile `
    -NoNewWindow `
    -PassThru

Write-Host "JTCC started — PID $($proc.Id)" -ForegroundColor Green
Write-Host "Log:   $logFile" -ForegroundColor DarkGray
Write-Host "Error: $errFile" -ForegroundColor DarkGray
Write-Host ""
Write-Host "State: logs\jtcc\_jtcc_state.json (confluence, signals)" -ForegroundColor DarkGray
Write-Host "Stop:  Stop-Process -Id $($proc.Id)" -ForegroundColor DarkGray

# ── Save PID ─────────────────────────────────────────────────
try {
    $pids = if (Test-Path $PidFile) { Get-Content $PidFile | ConvertFrom-Json -AsHashtable } else { @{} }
    $pids["jtcc"] = $proc.Id
    $pids | ConvertTo-Json | Set-Content $PidFile
} catch {
    # Non-fatal
}

Write-Host ""
Write-Host "Dashboard: strategies/confluence visible at /api/jtcc" -ForegroundColor Cyan
