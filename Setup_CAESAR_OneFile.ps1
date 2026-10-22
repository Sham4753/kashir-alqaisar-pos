$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# The embedded Python runtime and its Lib/site-packages are authoritative.
# pip is only a repair path when a required import is genuinely missing.
$env:PYTHONWARNINGS = "ignore"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PIP_NO_INPUT = "1"

$Wheelhouse = Join-Path $ScriptDir "offline_wheels"
$WebView2Runtime = Join-Path $ScriptDir "WebView2Runtime"
$Python = Join-Path $ScriptDir "python.exe"
$App = Join-Path $ScriptDir "app"
$Launcher = Join-Path $ScriptDir "caesar_desktop.py"
$Icon = Join-Path $App "caesar_icon.ico"
$PackageManifest = Join-Path $ScriptDir "embedded_packages_manifest.json"
$Out = Join-Path $ScriptDir "dist"
$Build = Join-Path $ScriptDir "build"
$BuildLog = Join-Path $ScriptDir "build_onedir.log"
if (Test-Path -LiteralPath $BuildLog) { Remove-Item -LiteralPath $BuildLog -Force -ErrorAction SilentlyContinue }

# The bundled interpreter is mandatory so the build is reproducible and offline.
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Embedded python.exe was not found next to this script."
}
if (-not (Test-Path -LiteralPath (Join-Path $ScriptDir "python312.dll"))) { throw "Embedded python312.dll is missing." }
if (-not (Test-Path -LiteralPath (Join-Path $ScriptDir "python312.zip"))) { throw "Embedded Python standard library python312.zip is missing." }

# Some Windows copies of the embeddable distribution do not honor the ._pth
# file after extraction/renaming. Make the bundled package directory explicit,
# without installing anything and without using the user's global Python.
$EmbeddedSitePackages = Join-Path $ScriptDir "Lib\site-packages"
if (Test-Path -LiteralPath $EmbeddedSitePackages) {
    $ExistingPythonPath = $env:PYTHONPATH
    if ($ExistingPythonPath) {
        $env:PYTHONPATH = $EmbeddedSitePackages + ";" + $ScriptDir + ";" + $ExistingPythonPath
    } else {
        $env:PYTHONPATH = $EmbeddedSitePackages + ";" + $ScriptDir
    }
    Write-Host ("Using embedded packages: " + $EmbeddedSitePackages)
} else {
    Write-Warning ("Embedded package directory was not found: " + $EmbeddedSitePackages)
}

if (-not (Test-Path -LiteralPath $Launcher)) { throw "caesar_desktop.py was not found." }
if (-not (Test-Path -LiteralPath $Icon)) { throw "app\caesar_icon.ico was not found." }
if (-not (Test-Path -LiteralPath (Join-Path $App "server.py"))) { throw "app\server.py was not found." }

# Run a native command without treating ordinary stderr warnings as terminating
# PowerShell errors. The actual success signal is the process exit code.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | Tee-Object -FilePath $BuildLog -Append | ForEach-Object { Write-Host $_ }
    } finally {
        $ErrorActionPreference = $previous
    }
    return $LASTEXITCODE
}

function Invoke-PythonModule([string[]]$Arguments) {
    $code = Invoke-Native $Python (@("-m") + $Arguments)
    if ($code -ne 0) {
        Write-Host ""
        Write-Host ("BUILD COMMAND FAILED (exit code " + $code + "). Full output: " + $BuildLog) -ForegroundColor Red
        if (Test-Path -LiteralPath $BuildLog) {
            Write-Host "---------------- LAST 80 BUILD LINES ----------------" -ForegroundColor Yellow
            Get-Content -LiteralPath $BuildLog -Tail 80 | ForEach-Object { Write-Host $_ }
            Write-Host "-------------------------------------------------------" -ForegroundColor Yellow
        }
        throw ("python -m " + ($Arguments -join " ") + " failed (exit code " + $code + "). See " + $BuildLog)
    }
}

function Test-PythonImport([string]$ModuleName) {
    # Import the module itself, not only find_spec: this catches broken package
    # copies and prints the exact interpreter/path used by the build.
    $ProbeSitePackages = $EmbeddedSitePackages.Replace('\', '\\').Replace("'", "\'")
    $ProbeRoot = $ScriptDir.Replace('\', '\\').Replace("'", "\'")
    $probe = "import importlib,sys; sys.path.insert(0,r'$ProbeSitePackages'); sys.path.insert(0,r'$ProbeRoot'); print('Python:',sys.executable); print('PackagePath:', ';'.join(sys.path)); importlib.import_module('$ModuleName')"
    $code = Invoke-Native $Python @("-c", $probe)
    return ($code -eq 0)
}

# Check the embedded environment as one explicit gate. When this succeeds, no
# pip command is allowed to run, even if offline_wheels is absent.
if (-not (Test-Path -LiteralPath (Join-Path $ScriptDir "Lib\site-packages"))) {
    throw "Embedded Python package directory is missing: Lib\site-packages"
}
if (-not (Test-Path -LiteralPath $PackageManifest)) { throw "Embedded package manifest is missing: embedded_packages_manifest.json" }
Write-Host ("Embedded package manifest found: " + $PackageManifest)
$RequiredPackages = @(
    @{ Package = "pyinstaller"; Import = "PyInstaller" },
    @{ Package = "pywebview"; Import = "webview" },
    @{ Package = "Flask"; Import = "flask" },
    @{ Package = "Pillow"; Import = "PIL" },
    @{ Package = "reportlab"; Import = "reportlab" },
    @{ Package = "arabic-reshaper"; Import = "arabic_reshaper" },
    @{ Package = "python-bidi"; Import = "bidi" },
    @{ Package = "Werkzeug"; Import = "werkzeug" },
    @{ Package = "Jinja2"; Import = "jinja2" },
    @{ Package = "MarkupSafe"; Import = "markupsafe" },
    @{ Package = "itsdangerous"; Import = "itsdangerous" },
    @{ Package = "click"; Import = "click" },
    @{ Package = "blinker"; Import = "blinker" },
    @{ Package = "pythonnet"; Import = "pythonnet" },
    @{ Package = "clr-loader"; Import = "clr_loader" },
    @{ Package = "proxy-tools"; Import = "proxy_tools" },
    @{ Package = "pywin32-ctypes"; Import = "win32ctypes" }
)
$CffiBackend = Get-ChildItem -LiteralPath $EmbeddedSitePackages -Filter "_cffi_backend*.pyd" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $CffiBackend) {
    throw "Embedded CFFI native backend (_cffi_backend*.pyd) was not found under '$EmbeddedSitePackages'."
}
Write-Host ("CFFI native backend found: " + $CffiBackend.FullName)
$MissingPackages = @()
foreach ($Requirement in $RequiredPackages) {
    if (Test-PythonImport $Requirement.Import) {
        Write-Host ("Embedded package ready: " + $Requirement.Package)
    } else {
        $MissingPackages += $Requirement
        Write-Warning ("Embedded package missing: " + $Requirement.Package)
    }
}

if ($MissingPackages.Count -eq 0) {
    Write-Host "Embedded Python environment is complete; skipping pip and offline_wheels installation." -ForegroundColor Green
} else {
    # Repair only genuinely missing imports. Do not ask for offline_wheels when
    # it is not present, and do not use the network unless explicitly allowed.
    if (-not (Test-Path -LiteralPath $Wheelhouse)) {
        throw ("Embedded Python environment is missing: " + (($MissingPackages | ForEach-Object { $_.Package }) -join ", ") +
               ". No offline_wheels directory was found. Add matching wheels only for the missing packages, then re-run.")
    }

    foreach ($Requirement in $MissingPackages) {
        $WheelMatches = @(Get-ChildItem -LiteralPath $Wheelhouse -Filter ($Requirement.Package + "*.whl") -File -ErrorAction SilentlyContinue)
        if ($WheelMatches.Count -eq 0) {
            throw ("Embedded package '" + $Requirement.Package + "' is missing and no matching wheel was found in '" + $Wheelhouse + "'.")
        }
        Write-Host ("Installing missing package " + $Requirement.Package + " from offline_wheels...")
        $code = Invoke-Native $Python @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "--disable-pip-version-check", "--no-input", $Requirement.Package)
        if ($code -ne 0 -or -not (Test-PythonImport $Requirement.Import)) {
            throw ("Offline installation failed for missing package " + $Requirement.Package + ".")
        }
    }
}

Write-Host "1/6 - Checking the WebView2 runtime..."
$RuntimeArguments = @()
if (Test-Path -LiteralPath $WebView2Runtime) {
    $RuntimeArguments = @("--add-data", ($WebView2Runtime + ";WebView2Runtime"))
    Write-Host ("Using local WebView2 runtime: " + $WebView2Runtime)
} else {
    Write-Warning "WebView2Runtime was not found. The built application will require WebView2 installed on Windows."
}

$LicenseDataArguments = @()
foreach ($licenseFile in @(".license", ".license_secret")) {
    $licensePath = Join-Path $ScriptDir $licenseFile
    if (Test-Path -LiteralPath $licensePath) {
        $LicenseDataArguments += @("--add-data", ($licensePath + ";app"))
        Write-Host ("Bundling license file: " + $licenseFile)
    }
}

Write-Host "2/6 - Compiling application sources..."
Invoke-PythonModule @("py_compile", (Join-Path $App "server.py"), (Join-Path $App "permissions.py"), $Launcher, (Join-Path $ScriptDir "generate_license.py"))

Write-Host "3/6 - Building the OneFolder executable (python -m PyInstaller)..."
$DataArguments = @("--add-data", ($App + ";app"))
$HiddenArguments = @(
    "--hidden-import", "app.server",
    "--hidden-import", "app.permissions",
    "--hidden-import", "_cffi_backend",
    "--collect-all", "cffi",
    "--collect-all", "webview"
)
$NativeArguments = @("--add-binary", ($CffiBackend.FullName + ";."))
$PyInstallerArguments = @("PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "CAESAR_POS", "--icon", $Icon, "--distpath", $Out, "--workpath", $Build, "--specpath", $Build) + $DataArguments + $RuntimeArguments + $LicenseDataArguments + $HiddenArguments + $NativeArguments + @($Launcher)
Invoke-PythonModule $PyInstallerArguments

$ProductDir = Join-Path $Out "CAESAR_POS"
$Exe = Join-Path $ProductDir "CAESAR_POS.exe"
if (-not (Test-Path -LiteralPath $Exe)) { throw "CAESAR_POS.exe was not created." }

Write-Host "4/6 - Copying the standalone license generator..."
Copy-Item -LiteralPath (Join-Path $ScriptDir "generate_license.py") -Destination (Join-Path $Out "generate_license.py") -Force

Write-Host "5/6 - Creating the commercial ZIP package..."
$Zip = Join-Path $ScriptDir "CAESAR_POS_OneFolder_Commercial_v4.zip"
if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
Compress-Archive -Path $ProductDir -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "6/6 - Build verification..."
if (-not (Test-Path -LiteralPath $Zip)) { throw "Commercial ZIP was not created." }
Write-Host ("OneFolder build complete: " + $Exe) -ForegroundColor Green
Write-Host ("Package complete: " + $Zip) -ForegroundColor Green
if (Test-Path -LiteralPath $Build) { Remove-Item -LiteralPath $Build -Recurse -Force -ErrorAction SilentlyContinue }
