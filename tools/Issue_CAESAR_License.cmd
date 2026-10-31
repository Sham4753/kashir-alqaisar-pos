@echo off
setlocal EnableExtensions

REM Vendor-only launcher. The private key and passphrase are never stored here.
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\python.exe"
set "GENERATOR=%ROOT%\generate_license.py"
set "PRIVATE_KEY=C:\CAESAR-Keys\caesar-vendor-private-v3.pem"

title CAESAR POS - License Issuer
cls
echo CAESAR POS - License Issuer
echo ==========================
echo Vendor tool only. Never include it in customer packages.
echo.

if not exist "%PYTHON%" (
    echo ERROR: Bundled python.exe was not found: "%PYTHON%"
    goto :finish_error
)
if not exist "%GENERATOR%" (
    echo ERROR: generate_license.py was not found: "%GENERATOR%"
    goto :finish_error
)
if not exist "%PRIVATE_KEY%" (
    echo ERROR: Vendor private key was not found: "%PRIVATE_KEY%"
    echo Keep the private key outside this repository and never send it to customers.
    goto :finish_error
)

set /p "MACHINE_ID=Enter the customer's Machine ID: "
if not defined MACHINE_ID (
    echo ERROR: Machine ID cannot be empty.
    goto :finish_error
)

pushd "%ROOT%" >nul
"%PYTHON%" "%GENERATOR%" --private-key "%PRIVATE_KEY%" --machine-id "%MACHINE_ID%" --no-pause
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" goto :finish_error

echo.
echo Copy the License ID and License Key above into the customer's app.
echo Never share the private key or its passphrase.
echo.
pause
exit /b 0

:finish_error
echo.
echo License was not issued. Check the error above; do not share the private key or passphrase.
echo.
pause
exit /b 1
