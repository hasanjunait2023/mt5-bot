' Launches jtcc_watchdog.ps1 with NO visible console.
' Scheduled Task runs this via wscript.exe (GUI subsystem) so no conhost
' window flashes every 5 min. WScript.Shell.Run with intWindowStyle=0
' starts PowerShell hidden; bWaitOnReturn=False returns immediately.
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\Junait\mt5 bot\jtcc_watchdog.ps1""", 0, False
Set sh = Nothing
