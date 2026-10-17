@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "ROOT=%~dp0"
set "REPORT=%ROOT%preflight-report.json"
set "PYTHON=%ROOT%python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo ============================================================
echo CAESAR POS - COMPREHENSIVE PRE-FLIGHT BUILD GATE
echo ============================================================

REM Hardware is required for the production build gate. Configure either:
REM   set CAESAR_PRINTER_HOST=192.168.1.50
REM   set CAESAR_PRINTER_PORT=9100
REM   set CAESAR_DRAWER_HOST=192.168.1.50
REM   set CAESAR_DRAWER_PORT=9100
REM or a USB/COM printer:
REM   set CAESAR_PRINTER_SERIAL=COM3

"%PYTHON%" "%ROOT%tools\comprehensive_preflight.py" --root "%ROOT%" --report "%REPORT%" --strict-hardware
if errorlevel 1 (
  echo.
  echo BUILD BLOCKED: pre-flight tests failed.
  echo Review: %REPORT%
  exit /b 1
)

echo.
echo PRE-FLIGHT PASSED. Starting EXE build...

if exist "%ROOT%Setup_CAESAR_OneFile.bat" (
  call "%ROOT%Setup_CAESAR_OneFile.bat"
  if errorlevel 1 exit /b %errorlevel%
  goto :success
)
if exist "%ROOT%Build_CAESAR_OneFile.bat" (
  call "%ROOT%Build_CAESAR_OneFile.bat"
  if errorlevel 1 exit /b %errorlevel%
  goto :success
)
if exist "%ROOT%Setup_CAESAR_OneFile.ps1" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%Setup_CAESAR_OneFile.ps1"
  if errorlevel 1 exit /b %errorlevel%
  goto :success
)

echo BUILD BLOCKED: no EXE build command was found.
echo Add Setup_CAESAR_OneFile.bat, Build_CAESAR_OneFile.bat, or Setup_CAESAR_OneFile.ps1.
exit /b 2

:success
echo EXE build completed after a clean pre-flight.
exit /b 0
