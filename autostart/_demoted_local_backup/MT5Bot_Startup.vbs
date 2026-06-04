Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & "C:\Users\Junait\mt5 bot\scripts\start_all_bots.ps1" & """", 0, False
