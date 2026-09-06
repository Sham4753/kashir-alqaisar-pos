@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%~dp0"
set "APP=%~dp0app"
set "LOG=%APP%\server_error.log"

REM Prefer the packaged native EXE when it exists. This prevents duplicate
REM server/browser launches when the user starts the system from Start or USB.
if exist "%ROOT%CAESAR_POS.exe" (
  start "CAESAR POS" "%ROOT%CAESAR_POS.exe"
  exit /b 0
)
if exist "%ROOT%dist\CAESAR_POS.exe" (
  start "CAESAR POS" "%ROOT%dist\CAESAR_POS.exe"
  exit /b 0
)

if not exist "%ROOT%python.exe" goto :missing
if not exist "%ROOT%python312.dll" goto :missing
if not exist "%ROOT%python312._pth" goto :missing
if not exist "%ROOT%Lib\site-packages\flask\__init__.py" goto :missing
if not exist "%APP%\server.py" goto :missing
if not exist "%APP%\index.html" goto :missing

REM إيقاف خادم كاشير قيصر سابق على المنفذ المحلي فقط.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1

REM تشغيل الخادم من المصدر الحالي مع تسجيل أي خطأ في app\server_error.log.
if exist "%LOG%" del /q "%LOG%" >nul 2>&1
start "" /b cmd /d /c ""%ROOT%python.exe" "%APP%\server.py" > "%LOG%" 2>&1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(12); do { $c=Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue; if($c){exit 0}; Start-Sleep -Milliseconds 250 } while((Get-Date) -lt $deadline); exit 1" >nul 2>&1
if not errorlevel 1 goto :open

echo.
echo [CAESAR] تعذر تشغيل الخادم.
echo راجع ملف الخطأ التالي:
echo %LOG%
echo.
if exist "%LOG%" type "%LOG%"
pause
exit /b 1

:open
REM افتح CAESAR كنافذة تطبيق مستقلة بلا تبويبات أو شريط متصفح.
set "APP_URL=http://127.0.0.1:8080/"
set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%LocalAppData%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%LocalAppData%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER goto :no_app_runtime
start "CAESAR POS" "%BROWSER%" --app="%APP_URL%" --new-window --window-size=1280,820
exit /b 0

:no_app_runtime
echo.
echo [CAESAR] لم يتم العثور على Microsoft Edge أو Google Chrome لتشغيل نافذة التطبيق.
echo ثبّت أحدهما ثم أعد تشغيل CAESAR.
if exist "%LOG%" type "%LOG%"
pause
exit /b 1

:missing
echo.
echo [CAESAR] ملفات Windows المطلوبة ناقصة من الحزمة.
echo يجب فك ضغط الأرشيف كاملًا، والتأكد من وجود python.exe وLib وapp داخل هذا المجلد:
echo %ROOT%
pause
exit /b 1
