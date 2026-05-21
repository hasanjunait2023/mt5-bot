# Runs Q3-Q9 one at a time, killing Chrome between each to release profile lock.
# Reads questions from nlm_questions.json to avoid encoding issues.
# Usage: powershell -File scripts\notebooklm_batch.ps1

$PROFILE_DIR = "$env:LOCALAPPDATA\notebooklm-mcp\Data\chrome_profile"
$SCRIPT_DIR = "C:\Users\Junait\mt5 bot\scripts"
$QUESTIONS_JSON = "$SCRIPT_DIR\nlm_questions.json"

$questions = Get-Content $QUESTIONS_JSON -Raw | ConvertFrom-Json

foreach ($item in $questions) {
  $n = $item.n
  $q = $item.q
  Write-Host "`n===== Running Q$n/9 =====" -ForegroundColor Cyan

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

  # Remove Chrome lock file if stale
  $lockFile = Join-Path $PROFILE_DIR "SingletonLock"
  if (Test-Path $lockFile) {
    Write-Host "  Removing stale Chrome lock..." -ForegroundColor Yellow
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
  }

  # Run the single-question script
  Write-Host "  Asking Q$n..."
  node "$SCRIPT_DIR\notebooklm_one.mjs" $n $q
  $exitCode = $LASTEXITCODE

  if ($exitCode -eq 0) {
    Write-Host "  Q$n saved OK" -ForegroundColor Green
  } else {
    Write-Host "  Q$n FAILED (exit $exitCode)" -ForegroundColor Red
  }

  Write-Host "  Waiting 6s before next question..."
  Start-Sleep -Seconds 6
}

Write-Host "`n=== ALL DONE ===" -ForegroundColor Green
