@echo off
setlocal
REM مشغل USB محمول: استخدم مسار موقع الفلاشة الحالي، لا مسارًا ثابتًا في Windows.
cd /d "%~dp0"
call "%~dp0Start.bat"
endlocal
