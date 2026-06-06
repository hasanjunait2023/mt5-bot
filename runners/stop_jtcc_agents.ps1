# Stop all JTCC agents

$patterns = @("trading_agents.jtcc.main", "trading_agents.jtcc.guardian",
              "trading_agents.jtcc.coach", "trading_agents.jtcc.digest")

$stopped = 0
foreach ($p in $patterns) {
    $procs = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        try { $_.CommandLine -like "*$p*" } catch { $false }
    }
    foreach ($proc in $procs) {
        try {
            Stop-Process -Id $proc.Id -Force
            Write-Host "Stopped $p (PID $($proc.Id))" -ForegroundColor Yellow
            $stopped++
        } catch {
            Write-Host "Failed to stop PID $($proc.Id): $_" -ForegroundColor Red
        }
    }
}
Write-Host ""
Write-Host "Stopped $stopped JTCC processes" -ForegroundColor Green
