@echo off
:: Start the Diary Sync Dashboard and Cloudflare Tunnel
:: This script is called from the Windows Startup folder

:: Start Flask dashboard
start /min "" pythonw "C:\Users\Derek\Documents\Coding\Python_Scripts\diary_sync\dashboard.py"

:: Give the dashboard a moment to start
timeout /t 3 /nobreak >nul

:: Start Cloudflare tunnel
start /min "" "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel run diary-sync
