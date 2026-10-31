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

$PosHtmlPath = Join-Path $App "index.html"
$PosCssPath = Join-Path $App "pos-modern.css"
if (-not (Test-Path -LiteralPath $PosHtmlPath) -or -not (Test-Path -LiteralPath $PosCssPath)) {
    throw "POS page or modern stylesheet is missing from app; refusing to build a stale interface."
}
$PosHtml = Get-Content -LiteralPath $PosHtmlPath -Raw
$PosCss = Get-Content -LiteralPath $PosCssPath -Raw
foreach ($CounterId in @('counterOrders', 'counterReady', 'counterSales')) {
    if (-not $PosHtml.Contains("id=`"$CounterId`"")) {
        throw "POS counter '$CounterId' is missing from app\index.html; refusing to build an incomplete interface."
    }
}
if (-not $PosHtml.Contains('/api/dashboard/counters') -or -not $PosCss.Contains('.counter-strip { display: grid !important;')) {
    throw "POS counter loading/visibility checks are missing; refusing to build an incomplete interface."
}
Write-Host "POS counter markup, API binding, and visibility fallback verified."

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

function Assert-Ed25519PublicKey([string]$KeyPath) {
    $probe = "import sys; from pathlib import Path; from cryptography.hazmat.primitives import serialization; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey; key=serialization.load_pem_public_key(Path(sys.argv[1]).read_bytes()); assert isinstance(key, Ed25519PublicKey), 'public key must be Ed25519'; print('Ed25519 public key validated')"
    $code = Invoke-Native $Python @("-c", $probe, $KeyPath)
    if ($code -ne 0) { throw ("LICENSE_PUBLIC_KEY_INVALID: expected a parseable Ed25519 public key: " + $KeyPath) }
}

function Test-CustomerArtifact([string]$Path, [string]$Root) {
    $rootFull = [IO.Path]::GetFullPath($Root)
    if (-not $rootFull.EndsWith([string][IO.Path]::DirectorySeparatorChar)) { $rootFull += [IO.Path]::DirectorySeparatorChar }
    $pathFull = [IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $relative = $pathFull.Substring($rootFull.Length).Replace('/', '\')
    $safeStatic = @(
        'factory_data.json', 'license_public_key.pem',
        'app\factory_data.json', '_internal\app\factory_data.json', 'runtime\_internal\app\factory_data.json',
        'app\license_public_key.pem', '_internal\app\license_public_key.pem', 'runtime\_internal\app\license_public_key.pem',
        'pythonnet\runtime\Python.Runtime.deps.json', '_internal\pythonnet\runtime\Python.Runtime.deps.json', 'runtime\_internal\pythonnet\runtime\Python.Runtime.deps.json'
    )
    if ($relative -in $safeStatic) { return $false }
    if ($relative -match '(?i)^(app\\vendor|_internal\\app\\vendor|runtime\\_internal\\app\\vendor)\\[^\\]+\.dist-info\\(license(?:\.txt)?|notice(?:\.txt)?|copying(?:\.txt)?)$') { return $false }
    $parts = $relative -split '\\'
    foreach ($part in $parts) {
        if ($part -match '(?i)secret|vault|backup|database|(^|[._-])data([._-]|$)|^(__pycache__|\.git)$') { return $true }
    }
    $name = [IO.Path]::GetFileName($relative).ToLowerInvariant()
    $extension = [IO.Path]::GetExtension($relative).ToLowerInvariant()
    if ($name -eq 'generate_license.py' -or $name -in @('.license', '.license_secret', 'license.secret', 'license.json', 'license.txt')) { return $true }
    if ($name -match '(?i)(private|secret).*\.(pem|key|p12|pfx)$') { return $true }
    if ($extension -in @('.json', '.json5', '.jsonc', '.jsonl', '.ndjson', '.csv', '.tsv', '.db', '.sqlite', '.sqlite3', '.log', '.bak', '.key', '.pem', '.p12', '.pfx', '.p7b', '.p7c', '.lic', '.license', '.licence', '.env')) { return $true }
    if ($name -match '(?i)\.(sqlite|sqlite3|db)([-.](wal|shm|journal))?(\.|$)' -or $name -match '(?i)\.log(\.|$)') { return $true }
    if ($name -match '(?i)(^|[._-])license([._-]|$)' -and $extension -notin @('.py', '.pyc')) { return $true }
    return $false
}

function Assert-NoCustomerArtifacts([string]$Root) {
    foreach ($entry in Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction Stop) {
        if (Test-CustomerArtifact -Path $entry.FullName -Root $Root) {
            throw ("CUSTOMER_BUILD_FORBIDDEN_FILE: sensitive or runtime data found in package tree: " + $entry.FullName)
        }
    }
}

function Remove-PythonBytecodeCache([string]$Root) {
    $cacheDirectories = @(Get-ChildItem -LiteralPath $Root -Directory -Filter '__pycache__' -Recurse -Force -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
    foreach ($cacheDirectory in $cacheDirectories) {
        if (Test-Path -LiteralPath $cacheDirectory.FullName -PathType Container) {
            Remove-Item -LiteralPath $cacheDirectory.FullName -Recurse -Force
        }
    }
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
    @{ Package = "cffi"; Import = "_cffi_backend" },
    @{ Package = "cryptography"; Import = "cryptography" },
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
$ManifestValidation = @'
import importlib.metadata as metadata
import json, struct, sys
from pathlib import Path
manifest_path, root = Path(sys.argv[1]), Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("format") != 1 or manifest.get("python") != "3.12" or manifest.get("source") != "Lib/site-packages":
    raise SystemExit("Embedded package manifest format, Python version, or source path is invalid")
for package in manifest.get("packages", []):
    expected = package.get("version")
    if expected and expected != "bundled":
        actual = metadata.version(package["distribution"])
        if actual != expected:
            raise SystemExit(f"{package['distribution']} version mismatch: manifest={expected}, embedded={actual}")
cffi = next((item for item in manifest.get("packages", []) if item.get("distribution", "").casefold() == "cffi"), None)
if not cffi or cffi.get("import") != "cffi" or cffi.get("windows_native_import") != "_cffi_backend" or cffi.get("windows_abi") != "CPython 3.12 x64":
    raise SystemExit("CFFI Windows ABI declaration is missing or invalid")
backend = root / cffi.get("windows_native_file", "")
if backend != root / "Lib" / "site-packages" / "_cffi_backend.cp312-win_amd64.pyd" or not backend.is_file():
    raise SystemExit("CFFI Windows CPython 3.12 x64 native backend file is missing or unexpected")
data = backend.read_bytes()
pe_offset = struct.unpack("<I", data[0x3C:0x40])[0]
if data[:2] != b"MZ" or data[pe_offset:pe_offset + 4] != b"PE\0\0" or struct.unpack("<H", data[pe_offset + 4:pe_offset + 6])[0] != 0x8664:
    raise SystemExit("CFFI native backend is not a Windows x64 PE binary")
print("Embedded manifest versions and CFFI Windows ABI verified")
'@
$ManifestValidationEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ManifestValidation))
$ManifestValidationCommand = "import base64; exec(base64.b64decode('$ManifestValidationEncoded'))"
$manifestCode = Invoke-Native $Python @("-c", $ManifestValidationCommand, $PackageManifest, $ScriptDir)
if ($manifestCode -ne 0) { throw "Embedded package manifest/version validation failed." }
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
        $code = Invoke-Native $Python @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "--disable-pip-version-check", "--no-input", "--upgrade", "--force-reinstall", "--target", $EmbeddedSitePackages, $Requirement.Package)
        if ($code -ne 0 -or -not (Test-PythonImport $Requirement.Import)) {
            throw ("Offline installation failed for missing package " + $Requirement.Package + ".")
        }
    }
}

$CffiBackend = Get-ChildItem -LiteralPath $EmbeddedSitePackages -Filter "_cffi_backend*.pyd" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $CffiBackend) {
    throw "Embedded CFFI native backend (_cffi_backend*.pyd) was not found under '$EmbeddedSitePackages' after package repair."
}
Write-Host ("CFFI native backend found: " + $CffiBackend.FullName)

Write-Host "1/6 - Checking the WebView2 runtime..."
$RuntimeArguments = @()
if (Test-Path -LiteralPath $WebView2Runtime) {
    $RuntimeArguments = @("--add-data", ($WebView2Runtime + ";WebView2Runtime"))
    Write-Host ("Using local WebView2 runtime: " + $WebView2Runtime)
} else {
    Write-Warning "WebView2Runtime was not found. The built application will require WebView2 installed on Windows."
}

$LicenseDataArguments = @()
$PublicKeyPath = Join-Path $App "license_public_key.pem"
if (-not (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
    throw "LICENSE_PUBLIC_KEY_MISSING: Create the vendor key pair and place only the public key at app\license_public_key.pem."
}
$null = Assert-Ed25519PublicKey $PublicKeyPath
Remove-PythonBytecodeCache $App
Assert-NoCustomerArtifacts $App
foreach ($forbiddenName in @(".license_secret", "license.secret", ".license", "license.txt", "license.json", "license_private_key.pem")) {
    $forbiddenPath = Join-Path $App $forbiddenName
    if (Test-Path -LiteralPath $forbiddenPath -PathType Leaf) {
        throw ("CUSTOMER_BUILD_FORBIDDEN_FILE: Remove this runtime/private file from app before packaging: " + $forbiddenName)
    }
}
Write-Host "Public license verification key found; no signing secret or customer license will be bundled."
Write-Host "2/6 - Compiling application sources..."
Invoke-PythonModule @("py_compile", (Join-Path $App "server.py"), (Join-Path $App "permissions.py"), $Launcher, (Join-Path $ScriptDir "generate_license.py"))
Remove-PythonBytecodeCache $App

Write-Host "3/6 - Building the OneFolder executable (python -m PyInstaller)..."
$DataArguments = @("--add-data", ($App + ";app"))
$HiddenArguments = @(
    "--hidden-import", "app.server",
    "--hidden-import", "app.permissions",
    "--hidden-import", "_cffi_backend",
    "--collect-all", "cffi",
    "--collect-all", "cryptography",
    "--collect-all", "webview"
)
$NativeArguments = @("--add-binary", ($CffiBackend.FullName + ";."))
$PyInstallerArguments = @("PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "CAESAR_POS", "--icon", $Icon, "--distpath", $Out, "--workpath", $Build, "--specpath", $Build) + $DataArguments + $RuntimeArguments + $LicenseDataArguments + $HiddenArguments + $NativeArguments + @($Launcher)
Invoke-PythonModule $PyInstallerArguments

$ProductDir = Join-Path $Out "CAESAR_POS"
$Exe = Join-Path $ProductDir "CAESAR_POS.exe"
if (-not (Test-Path -LiteralPath $Exe)) { throw "CAESAR_POS.exe was not created." }
$BundledIndex = Get-ChildItem -LiteralPath $ProductDir -Filter "index.html" -File -Recurse | Where-Object { $_.Directory.Name -eq "app" } | Select-Object -First 1
if (-not $BundledIndex) { throw "Bundled POS app\index.html was not found inside the executable package." }
$BundledAppDir = $BundledIndex.Directory.FullName
$BundledPublicKey = Join-Path $BundledAppDir "license_public_key.pem"
if (-not (Test-Path -LiteralPath $BundledPublicKey -PathType Leaf)) { throw "Bundled public license verification key is missing." }
$null = Assert-Ed25519PublicKey $BundledPublicKey
Remove-PythonBytecodeCache $ProductDir
Assert-NoCustomerArtifacts $ProductDir
$ForbiddenBundledFiles = @(Get-ChildItem -LiteralPath $ProductDir -File -Recurse -Force | Where-Object {
    $_.Name -in @(".license_secret", "license.secret", ".license", "license.txt", "license.json", "generate_license.py") -or
    $_.Name -match "(?i)(private|secret).*\.pem$"
})
if ($ForbiddenBundledFiles.Count -gt 0) {
    throw ("Customer package contains forbidden signing/license file(s): " + (($ForbiddenBundledFiles | ForEach-Object { $_.FullName }) -join ", "))
}
$BundledWelcome = Join-Path $BundledAppDir "welcome.html"
if (-not (Test-Path -LiteralPath $BundledWelcome -PathType Leaf)) { throw "Bundled app\welcome.html is missing; the account-selection screen cannot be verified." }
$WelcomeHtml = Get-Content -LiteralPath $BundledWelcome -Raw -Encoding UTF8
if (-not $WelcomeHtml.Contains('اختر حسابك للمتابعة')) { throw "Bundled welcome page is missing the account-selection screen text." }
$BundledHtml = Get-Content -LiteralPath $BundledIndex.FullName -Raw
$BundledCss = Get-Content -LiteralPath (Join-Path $BundledAppDir "pos-modern.css") -Raw
foreach ($CounterId in @('counterOrders', 'counterReady', 'counterSales')) {
    if (-not $BundledHtml.Contains("id=`"$CounterId`"")) {
        throw "Bundled POS counter '$CounterId' is missing from the built package."
    }
}
if (-not $BundledHtml.Contains('/api/dashboard/counters') -or -not $BundledCss.Contains('.counter-strip { display: grid !important;')) {
    throw "Bundled POS counter API binding or visibility fallback is missing from the built package."
}
if (-not $BundledCss.Contains('grid-template-columns: minmax(0, 1fr) minmax(450px, 480px) !important;')) {
    throw "Bundled POS desktop grid is stale; expected the two-track catalogue/order layout."
}
Write-Host "Built package contains the account-selection page and verified two-track POS layout."
Write-Host "Built package contains all three visible POS counter cards."
Write-Host "4/6 - Creating versioned customer and manual-update packages..."
$VersionMatch = [regex]::Match((Get-Content -LiteralPath (Join-Path $App "server.py") -Raw -Encoding UTF8), 'CURRENT_VERSION\s*=\s*"([A-Za-z0-9._-]+)"')
if (-not $VersionMatch.Success) { throw "CURRENT_VERSION is missing from app\server.py." }
$Version = $VersionMatch.Groups[1].Value
$UpdateBuilder = Join-Path $ScriptDir "tools\build_update_package.py"
$UpdateZip = Join-Path $Out ("CAESAR_POS_Update_v" + $Version + ".zip")
if (-not (Test-Path -LiteralPath $UpdateBuilder -PathType Leaf)) { throw "Manual update package builder is missing: $UpdateBuilder" }
$UpdateCode = Invoke-Native $Python @($UpdateBuilder, "--source", $ProductDir, "--version", $Version, "--output", $UpdateZip)
if ($UpdateCode -ne 0 -or -not (Test-Path -LiteralPath $UpdateZip -PathType Leaf)) { throw "Manual update package could not be created." }
$Zip = Join-Path $ScriptDir ("CAESAR_POS_OneFolder_Commercial_v" + $Version + ".zip")
if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
Compress-Archive -Path $ProductDir -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "5/6 - Build verification..."
if (-not (Test-Path -LiteralPath $Zip)) { throw "Commercial ZIP was not created." }
if (-not (Test-Path -LiteralPath $UpdateZip)) { throw "Manual update ZIP was not created." }
Write-Host "6/6 - Package contents verified; the signing key and license generator remain outside customer packages."
Write-Host ("OneFolder build complete: " + $Exe) -ForegroundColor Green
Write-Host ("Package complete: " + $Zip) -ForegroundColor Green
Write-Host ("Manual update package: " + $UpdateZip) -ForegroundColor Green
if (Test-Path -LiteralPath $Build) { Remove-Item -LiteralPath $Build -Recurse -Force -ErrorAction SilentlyContinue }
