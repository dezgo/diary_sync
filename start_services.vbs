Set WshShell = CreateObject("WScript.Shell")

' Start Flask dashboard (pythonw is already windowless)
WshShell.Run "pythonw ""C:\Users\Derek\Documents\Coding\Python_Scripts\diary_sync\dashboard.py""", 0, False

' Give the dashboard a moment to start
WScript.Sleep 3000

' Start Cloudflare tunnel (hidden)
WshShell.Run """C:\Program Files (x86)\cloudflared\cloudflared.exe"" tunnel run diary-sync", 0, False
