@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup_CAESAR_OneFile.ps1"
pause
