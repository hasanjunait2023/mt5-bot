# Batch-run the M3 Strength-Scalp EA in the MT5 Strategy Tester over a basket of
# pairs, 2yr, then parse PF / trades / net profit from each report.
param(
  [string[]]$Pairs = @("EURUSD","GBPUSD","AUDUSD","NZDUSD","USDJPY","USDCAD","USDCHF","EURJPY","GBPJPY","AUDJPY","EURGBP","EURAUD"),
  [string]$From = "2023.04.01",
  [string]$To   = "2026.06.01",
  [int]$Model   = 1
)
$base = "C:\Users\Junait\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
$term = "C:\Program Files\MetaTrader 5\terminal64.exe"
$repDir = "$base\tester_reports"
New-Item -ItemType Directory -Force $repDir | Out-Null
$results = @()

foreach($sym in $Pairs){
  $ini = "$base\tester_m3_$sym.ini"
  $rep = "tester_reports\M3SS_$sym"
  $cfg = @"
[Tester]
Expert=M3_StrengthScalp.ex5
Symbol=$sym
Period=M3
Model=$Model
FromDate=$From
ToDate=$To
Deposit=1000
Currency=USD
Leverage=500
Optimization=0
ShutdownTerminal=1
Report=$rep
ReplaceReport=1
"@
  Set-Content $ini $cfg -Encoding Unicode
  Remove-Item "$repDir\M3SS_$sym.htm" -ErrorAction SilentlyContinue
  Write-Host "[$([DateTime]::Now.ToString('HH:mm:ss'))] testing $sym $From..$To ..."
  $p = Start-Process $term -ArgumentList "/config:$ini" -PassThru
  $p.WaitForExit(900000) | Out-Null

  $htm = "$repDir\M3SS_$sym.htm"
  if(Test-Path $htm){
    $t = (Get-Content $htm -Raw -Encoding Unicode) -replace '<[^>]+>',' ' -replace '&nbsp;',' ' -replace '\s+',' '
    function GrabNum($k){ $m=[regex]::Match($t,[regex]::Escape($k)+'\s*:?\s*(-?[\d\.]+)'); if($m.Success){[double]$m.Groups[1].Value}else{$null} }
    $pf  = GrabNum 'Profit Factor'
    $np  = GrabNum 'Total Net Profit'
    $tr  = GrabNum 'Total Trades'
    $ep  = GrabNum 'Expected Payoff'
    $results += [PSCustomObject]@{ Symbol=$sym; Trades=$tr; PF=$pf; NetProfit=$np; ExpPayoff=$ep }
    Write-Host ("    {0}  PF={1}  trades={2}  net={3}" -f $sym,$pf,$tr,$np)
  } else {
    $results += [PSCustomObject]@{ Symbol=$sym; Trades=$null; PF=$null; NetProfit=$null; ExpPayoff=$null }
    Write-Host "    $sym  NO REPORT"
  }
}

Write-Host "`n================ M3 Strength-Scalp - 2yr MT5 Strategy Tester ================"
$results | Sort-Object { if($_.PF){$_.PF}else{-1} } -Descending | Format-Table -AutoSize
$pass = $results | Where-Object { $_.PF -ge 1.3 }
$tot  = ($results | Where-Object { $_.Trades } | Measure-Object Trades -Sum).Sum
Write-Host ("Pairs PF>=1.3: {0}/{1}   total trades: {2}" -f $pass.Count, $results.Count, $tot)
$results | ConvertTo-Json | Set-Content "$repDir\_m3ss_summary.json" -Encoding UTF8
Write-Host "Summary -> $repDir\_m3ss_summary.json"
