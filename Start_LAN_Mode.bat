@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "CAESAR_LAN=1"
set "CAESAR_PORT=8080"
REM Start.bat terminates any previous owner of port 8080 before serving the
REM current app\server.py and opening the current frontend.
call "%~dp0Start.bat"
endlocal
exit /b %errorlevel%
