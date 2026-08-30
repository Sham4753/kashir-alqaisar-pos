@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0POS_Source_Clean\Start.bat" (
    echo تعذر العثور على POS_Source_Clean\Start.bat.
    echo تأكد من فك ضغط المشروع كاملًا.
    pause
    exit /b 1
)
call "%~dp0POS_Source_Clean\Start.bat"
endlocal
