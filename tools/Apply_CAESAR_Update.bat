@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Apply_CAESAR_Update.ps1"
set "UPDATE_EXIT=%ERRORLEVEL%"
if not "%UPDATE_EXIT%"=="0" (
  echo.
  echo The update did not complete successfully. Review the message above.
)
echo.
pause
exit /b %UPDATE_EXIT%
