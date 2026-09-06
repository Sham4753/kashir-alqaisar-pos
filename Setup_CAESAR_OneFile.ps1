$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ملاحظة مهمة: نُبقي $ErrorActionPreference = "Stop" لأخطاء منطق هذا السكريبت
# نفسه (Test-Path/throw)، لكن كل استدعاء لأداة خارجية (pip/python/PyInstaller)
# يمرّ عبر Invoke-Native أدناه، التي تُحيّد هذا الإعداد مؤقتاً حول الاستدعاء.
# السبب: PowerShell قد يحوّل أي سطر يكتبه برنامج خارجي إلى stderr (بما فيها
# تحذيرات pip/PyInstaller غير القاتلة مثل "not on PATH" أو DeprecationWarning)
# إلى خطأ "منهي" طالما ErrorActionPreference=Stop فعّال، فيتوقف البناء عند أول
# تحذير عادي رغم أن الأداة نفسها نجحت (exit code = 0). الفحص الحقيقي للنجاح
# يبقى عبر $LASTEXITCODE فقط، وليس عبر وجود نص بمجرى الخطأ.
$env:PYTHONWARNINGS = "ignore"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PIP_NO_INPUT = "1"

$Wheelhouse = Join-Path $ScriptDir "offline_wheels"
$WebView2Runtime = Join-Path $ScriptDir "WebView2Runtime"
$Python = Join-Path $ScriptDir "python.exe"
$App = Join-Path $ScriptDir "app"
$Launcher = Join-Path $ScriptDir "caesar_desktop.py"
$Icon = Join-Path $App "caesar_icon.ico"
$Out = Join-Path $ScriptDir "dist"
$Build = Join-Path $ScriptDir "build"

# python.exe المضمّن بجانب هذا السكريبت هو المصدر الوحيد المعتمد؛ لا يعتمد
# البناء على متغيّر البيئة PATH إطلاقاً إلا كملاذ أخير إن حُذف بالخطأ.
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Warning "python.exe embedded copy was not found next to this script - falling back to PATH."
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCommand) { $Python = $PythonCommand.Source } else { $Python = $null }
}
if (-not $Python) { throw "python.exe was not found (neither embedded nor on PATH)." }
if (-not (Test-Path -LiteralPath $Launcher)) { throw "caesar_desktop.py was not found." }
if (-not (Test-Path -LiteralPath $Icon)) { throw "app\caesar_icon.ico was not found." }
if (-not (Test-Path -LiteralPath (Join-Path $App "server.py"))) { throw "app\server.py was not found." }

# يشغّل أمراً خارجياً وأي تحذير عادي يكتبه على stderr لا يوقف السكريبت؛ النجاح
# يُقاس فقط بـ $LASTEXITCODE بعد التشغيل. يُعاد ErrorActionPreference لحالته
# السابقة دائماً (حتى لو فشل الأمر) عبر try/finally.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
    } finally {
        $ErrorActionPreference = $previous
    }
    return $LASTEXITCODE
}

# كل استدعاء لبايثون يمر حصراً عبر "python -m <module>" الصريح (وليس عبر
# pyinstaller.exe أو أي أمر آخر قد يكون غير موجود بمتغير PATH).
function Invoke-PythonModule([string[]]$Arguments) {
    $code = Invoke-Native $Python (@("-m") + $Arguments)
    if ($code -ne 0) { throw ("python -m " + ($Arguments -join " ") + " failed (exit code " + $code + ").") }
}

function Test-PythonImport([string]$ModuleName) {
    $code = Invoke-Native $Python @("-c", "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)")
    return ($code -eq 0)
}

# فحص/تركيب أي حزمة بناء مفقودة (pyinstaller/pywebview/Flask) بدون أن يوقف
# البناء لأي سبب متعلق بالشبكة أو بتحذير عادي: مهلة قصيرة على pip، ومحاولة
# واحدة فقط أونلاين، وتحذيرات pip (مثل "not on PATH") لا توقف السكريبت أبداً.
$script:MissingPackages = @()
function Install-Package([string]$PackageName, [string]$ImportName) {
    if (Test-PythonImport $ImportName) {
        Write-Host ($PackageName + " is already installed locally.")
        return
    }
    if (Test-Path -LiteralPath $Wheelhouse) {
        Write-Host ("Installing " + $PackageName + " from offline_wheels (no network)...")
        $code = Invoke-Native $Python @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "--disable-pip-version-check", "--no-input", $PackageName)
        if ($code -eq 0 -and (Test-PythonImport $ImportName)) { return }
        Write-Warning ("Offline install failed for " + $PackageName + ".")
    }
    Write-Host ("Trying a single, time-limited online install for " + $PackageName + " (skips silently if there is no internet access)...")
    $code = Invoke-Native $Python @("-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--retries", "1", "--timeout", "8", $PackageName)
    if ($code -eq 0 -and (Test-PythonImport $ImportName)) { return }
    $script:MissingPackages += $PackageName
    Write-Warning ("Could not install " + $PackageName + " (no offline_wheels match and no usable internet connection).")
}

Write-Host "1/6 - Checking build dependencies..."
Install-Package "pyinstaller" "PyInstaller"
Install-Package "pywebview" "webview"
Install-Package "Flask" "flask"
if ($script:MissingPackages.Count -gt 0) {
    throw ("Missing required package(s): " + ($script:MissingPackages -join ", ") +
           ". Place matching .whl files under '" + $Wheelhouse + "' (offline install) or connect to the internet, then re-run this script.")
}

Write-Host "2/6 - Checking the WebView2 runtime..."
$RuntimeArguments = @()
if (Test-Path -LiteralPath $WebView2Runtime) {
    $RuntimeArguments = @("--add-data", ($WebView2Runtime + ";WebView2Runtime"))
    Write-Host ("Using local WebView2 runtime: " + $WebView2Runtime)
} else {
    Write-Warning "WebView2Runtime was not found. The built application will require WebView2 installed on Windows."
}

# ملفات الترخيص الاختيارية (.license / .license_secret) بجذر المشروع تُضمَّن
# تلقائياً داخل الحزمة عبر --add-data إن وُجدت، بدون أي تعديل يدوي على أمر البناء.
$LicenseDataArguments = @()
foreach ($licenseFile in @(".license", ".license_secret")) {
    $licensePath = Join-Path $ScriptDir $licenseFile
    if (Test-Path -LiteralPath $licensePath) {
        $LicenseDataArguments += @("--add-data", ($licensePath + ";app"))
        Write-Host ("Bundling license file: " + $licenseFile)
    }
}

Write-Host "3/6 - Compiling application sources..."
Invoke-PythonModule @("py_compile", (Join-Path $App "server.py"), (Join-Path $App "permissions.py"), $Launcher, (Join-Path $ScriptDir "generate_license.py"))

Write-Host "4/6 - Building the single-file executable (python -m PyInstaller)..."
$DataArguments = @("--add-data", ($App + ";app"))
$HiddenArguments = @("--hidden-import", "app.server", "--hidden-import", "app.permissions", "--collect-all", "webview")
$PyInstallerArguments = @("PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "CAESAR_POS", "--icon", $Icon, "--distpath", $Out, "--workpath", $Build, "--specpath", $Build) + $DataArguments + $RuntimeArguments + $LicenseDataArguments + $HiddenArguments + @($Launcher)
Invoke-PythonModule $PyInstallerArguments

$Exe = Join-Path $Out "CAESAR_POS.exe"
if (-not (Test-Path -LiteralPath $Exe)) { throw "CAESAR_POS.exe was not created." }

Write-Host "5/6 - Copying the standalone license generator..."
Copy-Item -LiteralPath (Join-Path $ScriptDir "generate_license.py") -Destination (Join-Path $Out "generate_license.py") -Force

Write-Host "6/6 - Creating the commercial ZIP package..."
$Zip = Join-Path $ScriptDir "CAESAR_POS_Commercial_v4.zip"
if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
Compress-Archive -Path (Join-Path $Out "*") -DestinationPath $Zip -CompressionLevel Optimal

Write-Host ("Build complete: " + $Exe) -ForegroundColor Green
Write-Host ("Package complete: " + $Zip) -ForegroundColor Green
if (Test-Path -LiteralPath $Build) { Remove-Item -LiteralPath $Build -Recurse -Force -ErrorAction SilentlyContinue }
