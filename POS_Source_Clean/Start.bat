@echo off
setlocal
cd /d "%~dp0"

REM تشغيل نسخة الواجهة الحالية من ملفات HTML/CSS/JS داخل مجلد app.
REM لا تستخدم QaisarDesktop.exe هنا حتى لا تظهر واجهة مضمّنة قديمة.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1

if not exist "%~dp0python.exe" (
    echo تعذر العثور على Python المرفق. تأكد من فك ضغط الحزمة كاملة.
    pause
    exit /b 1
)
if not exist "%~dp0app\server.py" (
    echo تعذر العثور على ملفات التطبيق. شغّل Start.bat من داخل مجلد POS_Source_Clean.
    pause
    exit /b 1
)

set "QAISAR_PORT=8080"
set "QAISAR_LAN=0"
start "Kashir Al-Qaisar Server" /min "%~dp0python.exe" "%~dp0app\server.py"
timeout /t 2 /nobreak >nul

set "URL=http://127.0.0.1:8080/index.html?v=20260831"
where msedge.exe >nul 2>&1
if %errorlevel%==0 (
    start "Kashir Al-Qaisar POS" msedge.exe --app="%URL%" --window-size=1280,820
) else (
    start "Kashir Al-Qaisar POS" "%URL%"
)

endlocal
