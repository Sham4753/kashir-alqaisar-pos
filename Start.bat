@echo off
setlocal
cd /d "%~dp0"

REM إيقاف أي خادم سابق يستمع على منفذ النظام المحلي فقط.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1

REM تشغيل نافذة التطبيق من النسخة المضمنة، دون الحاجة إلى تثبيت Python أو فتح متصفح كامل.
start "" /B "%~dp0app\QaisarDesktop.exe"

endlocal
