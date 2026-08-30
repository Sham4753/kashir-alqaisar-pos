@echo off
setlocal
cd /d "%~dp0"

REM تشغيل الخادم الحالي للوصول من الكاشير والهاتف داخل شبكة المطعم الخاصة.
if not exist "%~dp0..\python.exe" (
    echo تعذر العثور على Python المرفق. تأكد من فك ضغط الحزمة كاملة.
    pause
    exit /b 1
)
if not exist "%~dp0server.py" (
    echo تعذر العثور على server.py داخل مجلد app.
    pause
    exit /b 1
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1
set "QAISAR_LAN=1"
set "QAISAR_PORT=8080"
start "Kashir Al-Qaisar LAN Server" /min "%~dp0..\python.exe" "%~dp0server.py"
timeout /t 2 /nobreak >nul

set "URL=http://127.0.0.1:8080/index.html?v=20260831"
where msedge.exe >nul 2>&1
if %errorlevel%==0 (
    start "Kashir Al-Qaisar POS" msedge.exe --app="%URL%" --window-size=1280,820
) else (
    start "Kashir Al-Qaisar POS" "%URL%"
)

echo.
echo LAN mode has started using the current HTML/CSS/JS interface.
echo If Windows Firewall asks, allow access on Private networks only.
echo Use this computer's local IP with port 8080 on the waiter phone.
timeout /t 5 /nobreak >nul
endlocal
