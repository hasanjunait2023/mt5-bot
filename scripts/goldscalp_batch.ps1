# Runs goldscalp Q2-Q12 one at a time, killing Chrome between each.
# Q1 already in goldscalp_research.md - skip it.
# Usage: powershell -File scripts\goldscalp_batch.ps1

$PROFILE_DIR = "$env:LOCALAPPDATA\notebooklm-mcp\Data\chrome_profile"
$SCRIPT_DIR = "C:\Users\Junait\mt5 bot\scripts"
$QUESTIONS_JSON = "$SCRIPT_DIR\goldscalp_questions.json"

$questions = Get-Content $QUESTIONS_JSON -Raw | ConvertFrom-Json

foreach ($item in $questions) {
  $n = $item.n
  $q = $item.q
  Write-Host "`n===== Running Q$n/12 =====" -ForegroundColor Cyan
  Write-Host "  $($q.Substring(0, [Math]::Min(80, $q.Length)))..." -ForegroundColor Gray

  # Kill any Chrome holding the notebooklm profile
  $chromeProcs = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
  if ($chromeProcs) {
    foreach ($proc in $chromeProcs) {
      try {
        $wmi = Get-WmiObject Win32_Process -Filter "ProcessId=$($proc.Id)" -ErrorAction SilentlyContinue
        if ($wmi -and $wmi.CommandLine -like "*notebooklm*") {
          Write-Host "  Killing notebooklm Chrome PID $($proc.Id)" -ForegroundColor Yellow
          Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
      } catch {}
    }
    Start-Sleep -Seconds 3
  }

  # Remove stale Chrome lock file
  $lockFile = Join-Path $PROFILE_DIR "SingletonLock"
  if (Test-Path $lockFile) {
    Write-Host "  Removing stale Chrome lock..." -ForegroundColor Yellow
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
  }

  # Run single question
  Write-Host "  Asking Q$n (timeout: 4min)..."
  node "$SCRIPT_DIR\goldscalp_one.mjs" $n $q
  $exitCode = $LASTEXITCODE

  if ($exitCode -eq 0) {
    Write-Host "  Q$n saved OK" -ForegroundColor Green
  } else {
    Write-Host "  Q$n FAILED (exit $exitCode) - continuing" -ForegroundColor Red
  }

  Write-Host "  Waiting 8s before next question..."
  Start-Sleep -Seconds 8
}

Write-Host "`n=== ALL DONE ===" -ForegroundColor Green
$outFile = Join-Path "C:\Users\Junait\mt5 bot" "goldscalp_research.md"
Write-Host "Output: $outFile" -ForegroundColor Cyan
