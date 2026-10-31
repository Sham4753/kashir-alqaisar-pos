[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$testRoot = Join-Path $env:TEMP ('caesar-update-integration-' + [Guid]::NewGuid().ToString('N'))
$completed = $false

function Assert-Equal([string]$Actual, [string]$Expected, [string]$Message) {
    if ($Actual -cne $Expected) { throw "$Message (actual='$Actual', expected='$Expected')" }
}

function Invoke-Updater([string]$ScriptPath, [string]$TargetRoot) {
    $output = @(& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ScriptPath -InstallRoot $TargetRoot -NoPause 2>&1)
    $code = $LASTEXITCODE
    [PSCustomObject]@{ ExitCode = $code; Output = ($output | Out-String) }
}

try {
    $packageRoot = Join-Path $testRoot 'package'
    $unpackedRoot = Join-Path $testRoot 'unpacked'
    $sourceRoot = Join-Path $packageRoot 'payload\CAESAR_POS'
    New-Item -ItemType Directory -Path (Join-Path $sourceRoot '_internal'), (Join-Path $sourceRoot 'app') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot 'tools\Apply_CAESAR_Update.ps1') -Destination $packageRoot -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot 'tools\Apply_CAESAR_Update.bat') -Destination $packageRoot -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot 'tools\README_UPDATE_AR.txt') -Destination $packageRoot -Force
    [IO.File]::WriteAllText((Join-Path $sourceRoot 'CAESAR_POS.exe'), 'new executable payload')
    [IO.File]::WriteAllText((Join-Path $sourceRoot '_internal\runtime.txt'), 'new runtime payload')
    [IO.File]::WriteAllText((Join-Path $sourceRoot 'app\welcome.html'), 'new application payload')
    $systemDataAssembly = Join-Path $sourceRoot '_internal\pythonnet\runtime\System.Data.Common.dll'
    New-Item -ItemType Directory -Path (Split-Path -Parent $systemDataAssembly) -Force | Out-Null
    [IO.File]::WriteAllText($systemDataAssembly, 'approved .NET runtime assembly')
    $vendorLicense = Join-Path $sourceRoot 'app\vendor\qrcode-8.2.dist-info\LICENSE'
    New-Item -ItemType Directory -Path (Split-Path -Parent $vendorLicense) -Force | Out-Null
    [IO.File]::WriteAllText($vendorLicense, 'third-party license notice')
    $clickLicense = Join-Path $sourceRoot '_internal\click-8.4.2.dist-info\licenses\LICENSE.txt'
    New-Item -ItemType Directory -Path (Split-Path -Parent $clickLicense) -Force | Out-Null
    [IO.File]::WriteAllText($clickLicense, 'click third-party license notice')
    [IO.File]::WriteAllText((Join-Path $sourceRoot 'zzz_marker.bin'), 'last payload entry')

    $zipPath = Join-Path $testRoot 'valid-update.zip'
    Compress-Archive -Path (Join-Path $packageRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
    Expand-Archive -LiteralPath $zipPath -DestinationPath $unpackedRoot -Force
    $updateScript = Join-Path $unpackedRoot 'Apply_CAESAR_Update.ps1'
    $payloadRoot = Join-Path $unpackedRoot 'payload\CAESAR_POS'
    if (-not (Test-Path -LiteralPath $payloadRoot -PathType Container)) { throw 'Test ZIP has the wrong payload layout.' }

    # Success: replace program files while preserving Vault and unrelated legacy files.
    $successRoot = Join-Path $testRoot 'success-install'
    New-Item -ItemType Directory -Path (Join-Path $successRoot '_internal'), (Join-Path $successRoot 'app'), (Join-Path $successRoot 'CAESAR_Vault') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $successRoot 'CAESAR_POS.exe'), 'old executable')
    [IO.File]::WriteAllText((Join-Path $successRoot '_internal\runtime.txt'), 'old runtime')
    [IO.File]::WriteAllText((Join-Path $successRoot 'app\welcome.html'), 'old application')
    [IO.File]::WriteAllText((Join-Path $successRoot 'app\license.json'), 'local app license')
    [IO.File]::WriteAllText((Join-Path $successRoot 'app\old-only.txt'), 'keep old file')
    [IO.File]::WriteAllText((Join-Path $successRoot 'CAESAR_Vault\license.json'), 'vault license marker')
    [IO.File]::WriteAllText((Join-Path $successRoot 'CAESAR_Vault\data.json'), 'vault data marker')
    $success = Invoke-Updater $updateScript $successRoot
    if ($success.ExitCode -ne 0) { throw "Valid update did not apply: $($success.Output)" }
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot 'CAESAR_POS.exe'))) 'new executable payload' 'Executable was not updated'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot '_internal\runtime.txt'))) 'new runtime payload' 'Runtime file was not updated'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot '_internal\pythonnet\runtime\System.Data.Common.dll'))) 'approved .NET runtime assembly' 'pythonnet runtime assembly was not updated'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot 'app\welcome.html'))) 'new application payload' 'App file was not updated'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot 'app\vendor\qrcode-8.2.dist-info\LICENSE'))) 'third-party license notice' 'Third-party license notice was not updated'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot '_internal\click-8.4.2.dist-info\licenses\LICENSE.txt'))) 'click third-party license notice' 'Nested third-party license notice was not updated'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot 'app\license.json'))) 'local app license' 'Local license file changed'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot 'app\old-only.txt'))) 'keep old file' 'Unlisted old file was deleted'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot 'CAESAR_Vault\license.json'))) 'vault license marker' 'Vault license changed'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $successRoot 'CAESAR_Vault\data.json'))) 'vault data marker' 'Vault data changed'

    # Rollback: force a late path conflict and verify previous files are restored.
    $rollbackRoot = Join-Path $testRoot 'rollback-install'
    New-Item -ItemType Directory -Path (Join-Path $rollbackRoot '_internal'), (Join-Path $rollbackRoot 'app'), (Join-Path $rollbackRoot 'CAESAR_Vault'), (Join-Path $rollbackRoot 'zzz_marker.bin') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $rollbackRoot 'CAESAR_POS.exe'), 'rollback executable')
    [IO.File]::WriteAllText((Join-Path $rollbackRoot '_internal\runtime.txt'), 'rollback runtime')
    [IO.File]::WriteAllText((Join-Path $rollbackRoot 'app\welcome.html'), 'rollback application')
    [IO.File]::WriteAllText((Join-Path $rollbackRoot 'CAESAR_Vault\data.json'), 'rollback vault marker')
    $rollback = Invoke-Updater $updateScript $rollbackRoot
    if ($rollback.ExitCode -eq 0) { throw 'A forced destination conflict should fail the update.' }
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $rollbackRoot 'CAESAR_POS.exe'))) 'rollback executable' 'Executable did not roll back'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $rollbackRoot '_internal\runtime.txt'))) 'rollback runtime' 'Runtime file did not roll back'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $rollbackRoot 'app\welcome.html'))) 'rollback application' 'App file did not roll back'
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $rollbackRoot 'CAESAR_Vault\data.json'))) 'rollback vault marker' 'Rollback changed local data'

    # Reject a database sidecar before any file is modified.
    $unsafePayload = Join-Path $unpackedRoot 'payload\CAESAR_POS\app\restaurant.sqlite3-wal'
    [IO.File]::WriteAllText($unsafePayload, 'must be rejected')
    $unsafeRoot = Join-Path $testRoot 'unsafe-install'
    New-Item -ItemType Directory -Path (Join-Path $unsafeRoot '_internal') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $unsafeRoot 'CAESAR_POS.exe'), 'unsafe target unchanged')
    $unsafe = Invoke-Updater $updateScript $unsafeRoot
    if ($unsafe.ExitCode -eq 0) { throw 'An update containing a SQLite sidecar was accepted.' }
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $unsafeRoot 'CAESAR_POS.exe'))) 'unsafe target unchanged' 'Unsafe ZIP changed the target'

    Remove-Item -LiteralPath $unsafePayload -Force
    $unsafeLicensePayload = Join-Path $unpackedRoot 'payload\CAESAR_POS\app\customer-license.txt'
    [IO.File]::WriteAllText($unsafeLicensePayload, 'per-customer license key')
    $unsafeLicense = Invoke-Updater $updateScript $unsafeRoot
    if ($unsafeLicense.ExitCode -eq 0) { throw 'An update containing a customer license text file was accepted.' }
    Assert-Equal ([IO.File]::ReadAllText((Join-Path $unsafeRoot 'CAESAR_POS.exe'))) 'unsafe target unchanged' 'License-file rejection changed the target'

    Write-Host 'Windows updater integration passed: apply, third-party license notice, Vault preservation, rollback, and unsafe-payload rejection.' -ForegroundColor Green
    $completed = $true
} finally {
    if ($completed -and (Test-Path -LiteralPath $testRoot)) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    } else {
        Write-Warning "Updater integration artifacts kept for diagnosis: $testRoot"
    }
}
