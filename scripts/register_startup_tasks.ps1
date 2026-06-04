# MT5 Bot - Register all trading processes as Scheduled Tasks
# Uses schtasks.exe (no admin required for current-user tasks)

$python  = "C:\Users\Junait\AppData\Local\Programs\Python\Python312\python.exe"
$workdir = "C:\Users\Junait\mt5 bot"

# ── Dashboard (uvicorn, separate venv) ────────────────────────────────────────
$uvicorn   = "C:\Users\Junait\mt5 bot\dashboard\backend\.venv\Scripts\uvicorn.exe"
$dashDir   = "C:\Users\Junait\mt5 bot\dashboard\backend"
$dashDelay = 30

$dashXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>MT5 Bot - Dashboard API + UI</Description></RegistrationInfo>
  <Triggers>
    <BootTrigger><Delay>PT${dashDelay}S</Delay><Enabled>true</Enabled></BootTrigger>
    <LogonTrigger><Delay>PT${dashDelay}S</Delay><Enabled>true</Enabled></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$env:USERDOMAIN\$env:USERNAME</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
    <Enabled>true</Enabled>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$uvicorn</Command>
      <Arguments>main:app --host 0.0.0.0 --port 8000</Arguments>
      <WorkingDirectory>$dashDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$dashXmlPath = [System.IO.Path]::GetTempFileName() + ".xml"
$dashXml | Out-File -FilePath $dashXmlPath -Encoding Unicode
$dashResult = schtasks /Create /TN "MT5Bot-Dashboard" /XML $dashXmlPath /F 2>&1
Remove-Item $dashXmlPath -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) { Write-Host "[OK] MT5Bot-Dashboard" -ForegroundColor Green }
else { Write-Host "[FAIL] MT5Bot-Dashboard - $dashResult" -ForegroundColor Red }

# ── Trading agent tasks ───────────────────────────────────────────────────────
# Each task: name, python args, startup delay in seconds
$tasks = @(
    @{ Name="MT5Bot-Bridge";        Args="mt5_bridge\api_server.py --port 8090";                                                                                                                                                                                Delay=65 },
    @{ Name="MT5Bot-SignalEngine";  Args="-m trading_agents.signal_engine.engine";                                                                                                                                                                              Delay=90 },
    @{ Name="MT5Bot-JTCC-Main";     Args="-m trading_agents.jtcc.main";                                                                                                                                                                                        Delay=120 },
    @{ Name="MT5Bot-JTCC-Guardian"; Args="-m trading_agents.jtcc.guardian --interval 60";                                                                                                                                                                      Delay=150 },
    @{ Name="MT5Bot-JTCC-Coach";    Args="-m trading_agents.jtcc.coach --loop --interval 6";                                                                                                                                                                   Delay=150 },
    @{ Name="MT5Bot-JTCC-Digest";   Args="-m trading_agents.jtcc.digest --loop";                                                                                                                                                                               Delay=150 },
    @{ Name="MT5Bot-MTF-Trader";    Args="mt5_bridge/mtf_live_trader.py --pairs CADJPY EURJPY USDJPY GBPAUD BTCUSD AUDNZD USDCAD EURUSD AUDCHF NZDUSD EURNZD NZDJPY AUDCAD GBPJPY AUDUSD AUDJPY GBPUSD XAUUSD --risk 1.0 --dd 20.0 --maxdd 50.0 --maxtd 6"; Delay=120 }
)

$ok = 0; $fail = 0

foreach ($t in $tasks) {
    $name  = $t.Name
    $delaySec = $t.Delay
    $delayFmt = "0{0:D2}:{1:D2}" -f [int]($delaySec / 60), ($delaySec % 60)  # MM:SS

    # Build XML for task with two triggers: ONSTART + ONLOGON
    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>MT5 Bot - $name</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Delay>PT$($delaySec)S</Delay>
      <Enabled>true</Enabled>
    </BootTrigger>
    <LogonTrigger>
      <Delay>PT$([int]($delaySec * 0.75))S</Delay>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$env:USERDOMAIN\$env:USERNAME</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT2M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
    <Enabled>true</Enabled>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$python</Command>
      <Arguments>$($t.Args)</Arguments>
      <WorkingDirectory>$workdir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

    $xmlPath = [System.IO.Path]::GetTempFileName() + ".xml"
    $xml | Out-File -FilePath $xmlPath -Encoding Unicode

    $result = schtasks /Create /TN $name /XML $xmlPath /F 2>&1
    Remove-Item $xmlPath -ErrorAction SilentlyContinue

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] $name" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "[FAIL] $name - $result" -ForegroundColor Red
        $fail++
    }
}

Write-Host ""
Write-Host "Done: $ok registered, $fail failed" -ForegroundColor Cyan
Write-Host "Check: schtasks /Query /TN MT5Bot-SignalEngine"
