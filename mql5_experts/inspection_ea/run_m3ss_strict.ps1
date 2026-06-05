$base="C:\Users\Junait\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
$term="C:\Program Files\MetaTrader 5\terminal64.exe"
$rep="$base\tester_reports"
$pairs=@("USDJPY","GBPUSD","EURJPY","GBPJPY")
foreach($sym in $pairs){
  $ini="$base\strict_$sym.ini"
  $r="tester_reports\STRICT_$sym"
  $cfg=@"
[Tester]
Expert=M3_StrengthScalp.ex5
Symbol=$sym
Period=M3
Model=1
FromDate=2023.04.01
ToDate=2026.06.01
Deposit=1000
Currency=USD
Leverage=500
Optimization=0
ShutdownTerminal=1
Report=$r
ReplaceReport=1
[TesterInputs]
InpMinDiff=5
InpTpRR=2.0
InpAtrExpansion=1.2
"@
  Set-Content $ini $cfg -Encoding Unicode
  $h="$rep\STRICT_$sym.htm"
  if(Test-Path $h){ Remove-Item $h -Force }
  Write-Host "testing $sym (strict) ..."
  $p=Start-Process $term -ArgumentList "/config:$ini" -PassThru
  $p.WaitForExit(600000) | Out-Null
  if(Test-Path $h){
    $t=(Get-Content $h -Raw -Encoding Unicode) -replace '<[^>]+>',' ' -replace '&nbsp;',' ' -replace '\s+',' '
    $pf=[regex]::Match($t,'Profit Factor\s*:?\s*(-?[\d\.]+)').Groups[1].Value
    $tr=[regex]::Match($t,'Total Trades\s*:?\s*(\d+)').Groups[1].Value
    $np=[regex]::Match($t,'Total Net Profit\s*:?\s*(-?[\d\.]+)').Groups[1].Value
    Write-Host ("RESULT {0}  PF={1}  trades={2}  net={3}" -f $sym,$pf,$tr,$np)
  } else { Write-Host "RESULT $sym NO REPORT" }
}
