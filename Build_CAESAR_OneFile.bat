@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo CAESAR POS - OFFLINE ONEFOLDER BUILD
echo ============================================================

set "ROOT=%~dp0"
set "SETUP=%ROOT%Setup_CAESAR_OneFile.ps1"

if not exist "%SETUP%" (
  echo BUILD BLOCKED: Setup_CAESAR_OneFile.ps1 was not found.
  pause
  exit /b 2
)

for %%F in (python.exe python312.dll python312.zip app\server.py app\permissions.py app\caesar_icon.ico caesar_desktop.py embedded_packages_manifest.json) do (
  if not exist "%ROOT%%%F" (
    echo BUILD BLOCKED: missing file:
    echo %ROOT%%%F
    pause
    exit /b 2
  )
)

if not exist "%ROOT%Lib\site-packages" (
  echo BUILD BLOCKED: Lib\site-packages is missing.
  pause
  exit /b 2
)

echo.
echo Runtime files verified.
echo Starting PyInstaller OneFolder build...
echo.

powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%SETUP%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo BUILD FAILED with exit code %EXIT_CODE%.
  echo Full build log:
  echo %ROOT%build_onedir.log
  pause
  exit /b %EXIT_CODE%
)

if not exist "%ROOT%dist\CAESAR_POS\CAESAR_POS.exe" (
  echo.
  echo BUILD FAILED: dist\CAESAR_POS\CAESAR_POS.exe was not created.
  pause
  exit /b 3
)

echo.
echo BUILD SUCCESSFUL.
echo Output:
echo %ROOT%dist\CAESAR_POS\CAESAR_POS.exe
echo.
pause
exit /b 0
