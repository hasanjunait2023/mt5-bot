' MT5 Trading Bot ? Silent Auto-Starter
' Runs at Windows login with no visible window
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File """ & "c:\Users\Junait\mt5 bot\autostart\bot_launcher.ps1" & """", 0, False
Set objShell = Nothing
