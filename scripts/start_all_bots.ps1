# MT5 Bot - Start all trading processes (hidden windows)
# Called from Windows Startup folder on user logon

$root       = "C:\Users\Junait\mt5 bot"
$python     = "C:\Users\Junait\AppData\Local\Programs\Python\Python312\python.exe"
$dashPython = "$root\dashboard\backend\.venv\Scripts\python.exe"
$dashDir    = "$root\dashboard\backend"
$log        = "$root\logs\startup\startup_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
New-Item -ItemType Directory -Force -Path "$root\logs\startup" | Out-Null

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $log -Value $line
    Write-Host $line
}

function IsRunning($keyword) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -like "*$keyword*") { return $true }
    }
    return $false
}

# Launch from project root with system Python
function Launch($name, $args, $delaySec, $keyword) {
    if (IsRunning $keyword) {
        Log "[SKIP] $name already running"
        return
    }
    Start-Sleep -Seconds $delaySec
    Start-Process $python -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden
    Log "[START] $name"
}

# Launch with custom python/workdir (for dashboard backend which needs its own venv)
function LaunchFromDir($name, $pyExe, $args, $workDir, $delaySec, $keyword) {
    if (IsRunning $keyword) {
        Log "[SKIP] $name already running"
        return
    }
    Start-Sleep -Seconds $delaySec
    Start-Process $pyExe -ArgumentList $args -WorkingDirectory $workDir -WindowStyle Hidden
    Log "[START] $name"
}

Log "=== MT5 Bot startup sequence ==="
Log "Waiting 60s for MT5 terminal to connect..."
Start-Sleep -Seconds 60

# ── Infrastructure (must start before any agent that needs bridge/dashboard) ─
# MT5 bridge: system Python, project root, script path (no __init__.py needed)
Launch        "MT5Bot-Bridge"     "mt5_bridge\api_server.py --port 8090"                                                          5  "api_server"
# Dashboard: venv Python, dashboard/backend workdir, uvicorn as module
LaunchFromDir "MT5Bot-Dashboard"  $dashPython  "-m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info"  $dashDir  10  "uvicorn main:app"

# ── Core trading (MT5-dependent) ─────────────────────────────────────────────
Launch "MT5Bot-SignalEngine"  "-m trading_agents.signal_engine.engine"                                                                                                                                                                                              30  "signal_engine.engine"
Launch "MT5Bot-MTF-Trader"    "mt5_bridge/mtf_live_trader.py --pairs CADJPY EURJPY USDJPY GBPAUD BTCUSD AUDNZD USDCAD EURUSD AUDCHF NZDUSD EURNZD NZDJPY AUDCAD GBPJPY AUDUSD AUDJPY GBPUSD XAUUSD --risk 1.0 --dd 20.0 --maxdd 50.0 --maxtd 6"                 10  "mtf_live_trader"
Launch "MT5Bot-JTCC-Main"     "-m trading_agents.jtcc.main"                                                                                                                                                                                                        10  "jtcc.main"
Launch "MT5Bot-JTCC-Guardian" "-m trading_agents.jtcc.guardian --interval 60"                                                                                                                                                                                      10  "jtcc.guardian"
Launch "MT5Bot-JTCC-Coach"    "-m trading_agents.jtcc.coach --loop --interval 6"                                                                                                                                                                                    5  "jtcc.coach"
Launch "MT5Bot-JTCC-Digest"   "-m trading_agents.jtcc.digest --loop"                                                                                                                                                                                                5  "jtcc.digest"

# ── Paper-trade agents (MT5-dependent, start after JTCC) ─────────────────────
Launch "MT5Bot-Iconic-Agent"  "-m trading_agents.iconic.agent --paper"                                                                                                                                                                                             10  "iconic.agent"
Launch "MT5Bot-Scalp-Agent"   "-m trading_agents.scalp.agent --paper"                                                                                                                                                                                              10  "scalp.agent"

# ── Intelligence & management (MT5-independent) ───────────────────────────────
Launch "MT5Bot-Maic-Bot"      "-m trading_agents.maic_telegram_bot"                                                                                                                                                                                                 5  "maic_telegram_bot"
Launch "MT5Bot-Supervisor"    "-m trading_agents.supervisor_agent"                                                                                                                                                                                                   5  "supervisor_agent"
Launch "MT5Bot-EOD-Review"    "-m trading_agents.eod_review --loop"                                                                                                                                                                                                  5  "eod_review"
Launch "MT5Bot-Scout"         "-m trading_agents.strategy_scout.strategy_scout --loop --interval 24"                                                                                                                                                                 5  "strategy_scout.strategy_scout"

Log "=== Startup sequence complete ==="
