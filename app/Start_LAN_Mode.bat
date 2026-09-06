@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM Delegate to the root launcher so stale server processes are stopped and the
REM current app\server.py plus current app\index.html are always served.
call "%~dp0..\Start_LAN_Mode.bat"
endlocal
exit /b %errorlevel%
