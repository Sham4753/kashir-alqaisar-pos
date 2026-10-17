@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

REM Compatibility entrypoint for the recommended low-resource OneFolder build.
call "%~dp0Build_CAESAR_OneFile.bat"
exit /b %ERRORLEVEL%
