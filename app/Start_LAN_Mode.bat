@echo off
setlocal
REM Kashir Al-Qaisar local network mode: phone/tablet access over Wi-Fi only.
set QAISAR_LAN=1
set QAISAR_PORT=8080
start "Kashir Al-Qaisar LAN" "%~dp0QaisarDesktop.exe"
echo.
echo LAN mode has started. Keep this window open until the cashier opens.
echo If Windows Firewall asks, allow access on Private networks only.
timeout /t 5 >nul
