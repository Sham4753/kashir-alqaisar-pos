@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "ROOT=%~dp0"
set "SCRIPT=%ROOT%Install_Desktop_Icon.ps1"
set "APPDIR=%ROOT%app"

if not exist "%SCRIPT%" (
  echo ERROR: Missing Install_Desktop_Icon.ps1
  echo Extract the complete patch into the Kashir folder, then try again.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -AppDir "%APPDIR%"
if errorlevel 1 (
  echo.
  echo ERROR: Desktop shortcut was not created.
  echo Run this file from the fully extracted Kashir folder, not from inside a ZIP file.
  pause
  exit /b 1
)

echo.
echo SUCCESS: A shortcut named Kashir-AlQaisar was created on your Desktop.
pause
endlocal
