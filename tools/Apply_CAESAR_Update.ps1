param(
    [string]$InstallRoot,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Test-RelativePathAllowed([string] $RelativePath) {
    if ([string]::IsNullOrWhiteSpace($RelativePath)) { return $false }
    $normalized = $RelativePath.Replace('/', '\')
    if ([IO.Path]::IsPathRooted($normalized) -or $normalized -match '(^|\\)\.\.(\\|$)') { return $false }
    $parts = $normalized -split '\\'
    $knownStaticAsset = $normalized -in @(
        'app\factory_data.json', '_internal\app\factory_data.json', 'runtime\_internal\app\factory_data.json',
        'app\license_public_key.pem', '_internal\app\license_public_key.pem', 'runtime\_internal\app\license_public_key.pem',
        'pythonnet\runtime\Python.Runtime.deps.json', '_internal\pythonnet\runtime\Python.Runtime.deps.json', 'runtime\_internal\pythonnet\runtime\Python.Runtime.deps.json'
    )
    if ($knownStaticAsset) {
        foreach ($part in $parts[0..($parts.Length - 2)]) {
            $parent = $part.ToLowerInvariant()
            if ($parent -match 'secret|vault|log|database|(^|[._-])data([._-]|$)' -or
                $parent -in @('license', 'licenses', 'backup', 'backups', 'sqlite', 'sqlite3', 'db', '__pycache__')) { return $false }
        }
        return $true
    }
    foreach ($part in $parts) {
        $lower = $part.ToLowerInvariant()
        if ($lower -match 'secret|vault|log|database|(^|[._-])data([._-]|$)' -or
            $lower -in @('license', 'licenses', 'backup', 'backups', 'sqlite', 'sqlite3', 'db', '__pycache__')) { return $false }
    }
    $name = [IO.Path]::GetFileName($normalized).ToLowerInvariant()
    $extension = [IO.Path]::GetExtension($normalized).ToLowerInvariant()
    if ($name -eq 'generate_license.py' -or $extension -in @('.json', '.json5', '.jsonc', '.jsonl', '.ndjson', '.csv', '.tsv', '.db', '.sqlite', '.sqlite3', '.log', '.bak', '.key', '.pem', '.p12', '.pfx', '.p7b', '.p7c', '.env', '.lic', '.license', '.licence')) { return $false }
    if ($name -match 'license' -and $extension -notin @('.py', '.pyc')) { return $false }
    if ($name -match '\.(sqlite|sqlite3|db)([-.](wal|shm|journal))?(\.|$)') { return $false }
    if ($name -match '\.log(\.|$)') { return $false }
    return $true
}

function Test-OneFolder([string] $Folder) {
    if (-not (Test-Path -LiteralPath $Folder -PathType Container)) { return $false }
    $exe = Join-Path $Folder 'CAESAR_POS.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { return $false }
    foreach ($relative in @('app', '_internal', 'runtime\_internal')) {
        if (Test-Path -LiteralPath (Join-Path $Folder $relative) -PathType Container) { return $true }
    }
    return $false
}

function Assert-NoReparsePath([string] $Root, [string] $RelativePath) {
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $current = $fullRoot
    $segments = $RelativePath.Replace('/', '\').Split('\')
    for ($i = 0; $i -lt $segments.Length; $i++) {
        $current = Join-Path $current $segments[$i]
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "رفض آمن: يوجد رابط/مسار معاد توجيهه داخل مسار التحديث: $current"
            }
        }
    }
}

$workRoot = $null
$keepWorkRoot = $false
$scriptExitCode = 0
$changed = New-Object System.Collections.Generic.List[object]

try {
    $payloadRoot = Join-Path $PSScriptRoot 'payload\CAESAR_POS'
    if (-not (Test-OneFolder $payloadRoot)) {
        throw 'حزمة التحديث غير صالحة: يجب أن يحتوي payload\CAESAR_POS على CAESAR_POS.exe ومجلد app أو _internal.'
    }

    $files = @(Get-ChildItem -LiteralPath $payloadRoot -File -Recurse -Force | Sort-Object FullName)
    if ($files.Count -eq 0) { throw 'حزمة التحديث فارغة.' }
    foreach ($directory in @(Get-ChildItem -LiteralPath $payloadRoot -Directory -Recurse -Force)) {
        if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "حزمة غير صالحة: لا يُسمح بمجلدات مرتبطة أو معاد توجيهها: $($directory.FullName)"
        }
    }
    $payloadEntries = New-Object System.Collections.Generic.List[object]
    foreach ($file in $files) {
        if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "حزمة غير صالحة: لا يُسمح بروابط الملفات: $($file.FullName)"
        }
        $relative = $file.FullName.Substring($payloadRoot.TrimEnd('\').Length).TrimStart('\')
        if (-not (Test-RelativePathAllowed $relative)) {
            throw "حزمة غير صالحة: تحتوي ملفًا ممنوعًا أو بيانات/ترخيصًا: $relative"
        }
        $payloadEntries.Add([pscustomobject]@{ Relative = $relative; Source = $file.FullName })
    }

    if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
        Add-Type -AssemblyName System.Windows.Forms
        $picker = New-Object System.Windows.Forms.FolderBrowserDialog
        $picker.Description = 'اختر مجلد CAESAR POS الحالي الذي يحتوي على CAESAR_POS.exe'
        $picker.ShowNewFolderButton = $false
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            Write-Host 'تم الإلغاء؛ لم يتم تغيير أي ملف.'
            exit 0
        }
        $targetRoot = [IO.Path]::GetFullPath($picker.SelectedPath).TrimEnd('\')
    } else {
        $targetRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
    }
    if (-not (Test-OneFolder $targetRoot)) {
        throw 'المجلد المحدد ليس تثبيت CAESAR POS صالحًا: يلزم CAESAR_POS.exe ومجلد app أو _internal.'
    }
    $targetRootItem = Get-Item -LiteralPath $targetRoot -Force
    if (($targetRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'رفض آمن: مجلد التثبيت المحدد رابط أو مسار معاد توجيهه.'
    }
    if ([string]::Equals($targetRoot, [IO.Path]::GetFullPath($payloadRoot).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'لا يمكن اختيار مجلد payload كمجلد تثبيت.'
    }

    foreach ($entry in $payloadEntries) { Assert-NoReparsePath $targetRoot $entry.Relative }

    $targetExe = [IO.Path]::GetFullPath((Join-Path $targetRoot 'CAESAR_POS.exe'))
    $running = @(Get-CimInstance Win32_Process -Filter "Name = 'CAESAR_POS.exe'" -ErrorAction Stop | Where-Object {
        $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $targetExe, [StringComparison]::OrdinalIgnoreCase)
    })
    foreach ($process in $running) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 300
        $stillRunning = @(Get-CimInstance Win32_Process -Filter "Name = 'CAESAR_POS.exe'" -ErrorAction Stop | Where-Object {
            $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $targetExe, [StringComparison]::OrdinalIgnoreCase)
        })
    } while ($stillRunning.Count -gt 0 -and (Get-Date) -lt $deadline)
    if ($stillRunning.Count -gt 0) { throw 'تعذر إيقاف CAESAR POS من مجلد التثبيت المحدد؛ لم يبدأ التحديث.' }

    $parent = Split-Path -Parent $targetRoot
    $workRoot = Join-Path $parent ('.CAESAR_POS_update_' + [Guid]::NewGuid().ToString('N'))
    $stageRoot = Join-Path $workRoot 'stage'
    $backupRoot = Join-Path $workRoot 'rollback'
    New-Item -ItemType Directory -Path $stageRoot, $backupRoot -Force | Out-Null

    # Stage and hash-check all payload files before modifying the installation.
    foreach ($entry in $payloadEntries) {
        $stagedPath = Join-Path $stageRoot $entry.Relative
        $stagedParent = Split-Path -Parent $stagedPath
        if (-not (Test-Path -LiteralPath $stagedParent -PathType Container)) { New-Item -ItemType Directory -Path $stagedParent -Force | Out-Null }
        Copy-Item -LiteralPath $entry.Source -Destination $stagedPath -Force
        $sourceHash = (Get-FileHash -LiteralPath $entry.Source -Algorithm SHA256).Hash
        $stageHash = (Get-FileHash -LiteralPath $stagedPath -Algorithm SHA256).Hash
        if ($sourceHash -ne $stageHash) { throw "فشل التحقق من النسخ المرحلي: $($entry.Relative)" }
    }

    Write-Host ("سيتم تحديث ملفات البرنامج فقط. عدد الملفات: " + $payloadEntries.Count)
    foreach ($entry in $payloadEntries) {
        $destination = Join-Path $targetRoot $entry.Relative
        Assert-NoReparsePath $targetRoot $entry.Relative
        if (Test-Path -LiteralPath $destination -PathType Container) {
            throw "يتعذر التحديث لأن مسار ملف البرنامج يشير إلى مجلد: $($entry.Relative)"
        }
        $destinationParent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        }
        $backupPath = Join-Path $backupRoot $entry.Relative
        $hadOriginal = Test-Path -LiteralPath $destination -PathType Leaf
        if ($hadOriginal) {
            $backupParent = Split-Path -Parent $backupPath
            if (-not (Test-Path -LiteralPath $backupParent -PathType Container)) { New-Item -ItemType Directory -Path $backupParent -Force | Out-Null }
            Copy-Item -LiteralPath $destination -Destination $backupPath -Force
            $originalHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
            $backupHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
            if ($originalHash -ne $backupHash) { throw "تعذر التحقق من نسخة الاسترداد: $($entry.Relative)" }
        }
        $changed.Add([pscustomobject]@{ Relative = $entry.Relative; HadOriginal = $hadOriginal })
        Copy-Item -LiteralPath (Join-Path $stageRoot $entry.Relative) -Destination $destination -Force
        $installedHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
        $expectedHash = (Get-FileHash -LiteralPath (Join-Path $stageRoot $entry.Relative) -Algorithm SHA256).Hash
        if ($installedHash -ne $expectedHash) { throw "فشل التحقق بعد استبدال الملف: $($entry.Relative)" }
    }

    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    $workRoot = $null
    Write-Host ''
    Write-Host 'نجح تحديث ملفات CAESAR POS. ابدأ البرنامج يدويًا من اختصارك أو من CAESAR_POS.exe.' -ForegroundColor Green
    Write-Host 'لم يتم تشغيل البرنامج تلقائيًا، ولم تُحذف ملفات Vault أو الترخيص أو الملفات الأخرى.'
}
catch {
    $failure = $_.Exception.Message
    $scriptExitCode = 1
    $rollbackErrors = New-Object System.Collections.Generic.List[string]
    if ($changed.Count -gt 0 -and $workRoot -and (Test-Path -LiteralPath $workRoot)) {
        for ($i = $changed.Count - 1; $i -ge 0; $i--) {
            $item = $changed[$i]
            $destination = Join-Path $targetRoot $item.Relative
            try {
                if ($item.HadOriginal) {
                    $backupPath = Join-Path (Join-Path $workRoot 'rollback') $item.Relative
                    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) { throw "نسخة الاسترداد غير موجودة: $($item.Relative)" }
                    Copy-Item -LiteralPath $backupPath -Destination $destination -Force
                } elseif (Test-Path -LiteralPath $destination -PathType Leaf) {
                    Remove-Item -LiteralPath $destination -Force
                }
            } catch {
                $rollbackErrors.Add("$($item.Relative): $($_.Exception.Message)")
            }
        }
    }
    Write-Error "فشل التحديث: $failure" -ErrorAction Continue
    if ($rollbackErrors.Count -gt 0) {
        $keepWorkRoot = $true
        Write-Error ("تعذر إكمال الاسترداد لبعض ملفات البرنامج. احتُفظ بنسخة الاسترداد هنا: " + $workRoot + " | " + ($rollbackErrors -join '; ')) -ErrorAction Continue
    } else {
        Write-Host 'أُعيدت ملفات البرنامج السابقة التي كانت ستُستبدل. لم تُحذف الملفات الأخرى.' -ForegroundColor Yellow
    }
}
finally {
    if ($workRoot -and -not $keepWorkRoot -and (Test-Path -LiteralPath $workRoot)) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
if (-not $NoPause) { Read-Host 'اضغط Enter للإغلاق' }
exit $scriptExitCode
