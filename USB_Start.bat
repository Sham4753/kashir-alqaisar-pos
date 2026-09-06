@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist "%~dp0USB_Start.vbs" (
  echo [CAESAR] USB_Start.vbs is missing. The package was not extracted completely.
  pause
  exit /b 1
)
rem Delegate immediately to the hidden Windows Script Host launcher.
start "" /b wscript.exe "%~dp0USB_Start.vbs"
endlocal
exit /b 0
