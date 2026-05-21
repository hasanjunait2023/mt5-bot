# =============================================================
# JTCC Full Stack Launcher - main + guardian + coach + digest
# Idempotent: only starts agents that aren't already running
# =============================================================

param(
    [switch]$DryRun,
    [switch]$GuardianOnly,
    [switch]$Force
)

$LogDir = "logs\jtcc"
$PidFile = "logs\_agent_pids.json"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "   JTCC Full Stack - Signal Engine + Self-Healing             " -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

function Get-RunningJtccAgent {
    param([string]$NamePattern)
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*$NamePattern*"
    } | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
}

function Start-JtccAgent {
    param(
        [string]$Name,
        [string[]]$ArgList,
        [string]$Pattern
    )

    $existing = Get-RunningJtccAgent -NamePattern $Pattern
    if ($existing -and -not $Force) {
        Write-Host "[$Name] already running (PID $($existing[0].Id))" -ForegroundColor Yellow
        return $existing[0].Id
    }
    if ($existing -and $Force) {
        Write-Host "[$Name] Force-stopping existing (PID $($existing[0].Id))..." -ForegroundColor Yellow
        $existing | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }

    $logFile = "$LogDir\$Name.log"
    $errFile = "$LogDir\$Name.err.log"
    $proc = Start-Process python -ArgumentList $ArgList -RedirectStandardOutput $logFile -RedirectStandardError $errFile -NoNewWindow -PassThru
    Write-Host "[$Name] started - PID $($proc.Id) | Log: $logFile" -ForegroundColor Green
    return $proc.Id
}

$pids = @{}

if (-not $GuardianOnly) {
    $mainArgs = @("-m", "trading_agents.jtcc.main")
    if ($DryRun) { $mainArgs += "--dry-run" }
    $pids["jtcc_main"] = Start-JtccAgent -Name "jtcc_main" -ArgList $mainArgs -Pattern "trading_agents.jtcc.main"
}

$pids["jtcc_guardian"] = Start-JtccAgent -Name "jtcc_guardian" -ArgList @("-m", "trading_agents.jtcc.guardian", "--interval", "60") -Pattern "trading_agents.jtcc.guardian"

if (-not $GuardianOnly) {
    $pids["jtcc_coach"] = Start-JtccAgent -Name "jtcc_coach" -ArgList @("-m", "trading_agents.jtcc.coach", "--loop", "--interval", "6") -Pattern "trading_agents.jtcc.coach"
    $pids["jtcc_digest"] = Start-JtccAgent -Name "jtcc_digest" -ArgList @("-m", "trading_agents.jtcc.digest", "--loop") -Pattern "trading_agents.jtcc.digest"
}

# Watchdog loop (PowerShell, not python) - keeps bridge + stack alive while PC is on
$wdRunning = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*jtcc_watchdog.ps1*-Loop*" }
if ($wdRunning -and -not $Force) {
    Write-Host "[jtcc_watchdog] already running (PID $($wdRunning[0].ProcessId))" -ForegroundColor Yellow
} else {
    if ($wdRunning -and $Force) { $wdRunning | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }
    $wdProc = Start-Process powershell -ArgumentList @("-NoProfile","-WindowStyle","Hidden","-ExecutionPolicy","Bypass","-File","$PSScriptRoot\jtcc_watchdog.ps1","-Loop") -WindowStyle Hidden -PassThru
    $pids["jtcc_watchdog"] = $wdProc.Id
    Write-Host "[jtcc_watchdog] started - PID $($wdProc.Id) | self-heals bridge + stack every 5min" -ForegroundColor Green
}

# Save PID map
try {
    $existingPids = if (Test-Path $PidFile) { Get-Content $PidFile | ConvertFrom-Json -AsHashtable } else { @{} }
    foreach ($k in $pids.Keys) { $existingPids[$k] = $pids[$k] }
    $existingPids | ConvertTo-Json | Set-Content $PidFile
} catch { }

Write-Host ""
$mode = if ($DryRun) { "DRY RUN" } else { "LIVE" }
Write-Host "JTCC stack online ($mode)" -ForegroundColor Cyan
Write-Host "  - main      : signal engine (4-layer pipeline)" -ForegroundColor DarkGray
Write-Host "  - guardian  : watchdog (errors, latency, dead-process detection)" -ForegroundColor DarkGray
if (-not $GuardianOnly) {
    Write-Host "  - coach     : 6h analysis + improvement proposals" -ForegroundColor DarkGray
    Write-Host "  - digest    : daily summary @ 00:30 BD" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Dashboard: /jtcc (equity curve, heatmap, latency, coach proposals)" -ForegroundColor Cyan
Write-Host "Stop all:  .\stop_jtcc_agents.ps1" -ForegroundColor DarkGray
