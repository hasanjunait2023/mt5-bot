' TradingView CDP Auto-Starter — launches TV Desktop with --remote-debugging-port=9222
' so Claude Code MCP and any trading agent can connect to CDP on 127.0.0.1:9222.
' Runs hidden at Windows logon. ActivateApplication needs an interactive session, so logon (not boot).
Set objShell = CreateObject("WScript.Shell")
' Wait 90s for desktop + MT5/bots to settle before (re)launching TV with CDP.
WScript.Sleep 90000
objShell.Run "powershell.exe -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File ""C:\Users\Junait\tradingview-mcp\launch_tv_cdp.ps1""", 0, False
Set objShell = Nothing
