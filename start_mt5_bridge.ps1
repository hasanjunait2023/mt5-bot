# MT5 FastAPI Bridge launcher - serves OHLCV bars + trade exec for JTCC

param([int]$Port = 8090, [switch]$Force)

$LogDir = "logs\jtcc"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }

# Idempotency: check if bridge already running
$existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*mt5_bridge.api_server*"
}

if ($existing -and -not $Force) {
    Write-Host "MT5 bridge already running (PID $($existing.ProcessId))" -ForegroundColor Yellow
    exit 0
}
if ($existing -and $Force) {
    Stop-Process -Id $existing.ProcessId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

$logFile = "$LogDir\mt5_bridge.log"
$errFile = "$LogDir\mt5_bridge.err.log"

$proc = Start-Process python -ArgumentList @("-m", "mt5_bridge.api_server", "--port", $Port) `
    -RedirectStandardOutput $logFile -RedirectStandardError $errFile -NoNewWindow -PassThru

Write-Host "MT5 bridge started - PID $($proc.Id) | http://localhost:$Port" -ForegroundColor Green
Write-Host "  /health, /account/info, /bars/{symbol}, /tick/{symbol}" -ForegroundColor DarkGray
Write-Host "  /positions/open, /trade/open, /trade/close" -ForegroundColor DarkGray
Write-Host "Log: $logFile" -ForegroundColor DarkGray
