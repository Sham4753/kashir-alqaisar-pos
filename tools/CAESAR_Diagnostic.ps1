[CmdletBinding()]
param(
    [string]$CanonicalRoot = "C:\CAESAR_POS",
    [int]$Port = 8080,
    [switch]$IncludeAllUserFiles
)

$ErrorActionPreference = 'SilentlyContinue'
$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell

function Test-PathInfo([string]$Path) {
    $exists = Test-Path -LiteralPath $Path
    [PSCustomObject]@{
        Path = $Path
        Exists = $exists
        Length = if ($exists -and (Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue).PSIsContainer -eq $false) { (Get-Item -LiteralPath $Path).Length } else { $null }
        LastWriteTime = if ($exists) { (Get-Item -LiteralPath $Path).LastWriteTime } else { $null }
    }
}

Write-Host '=== CAESAR POS diagnostic (no secrets printed) ===' -ForegroundColor Cyan
Write-Host "CanonicalRoot: $CanonicalRoot"
Write-Host "Desktop: $desktop"

Write-Host "`n=== Canonical runtime ===" -ForegroundColor Cyan
@(
    (Test-PathInfo $CanonicalRoot),
    (Test-PathInfo (Join-Path $CanonicalRoot 'Start.bat')),
    (Test-PathInfo (Join-Path $CanonicalRoot 'launch.vbs')),
    (Test-PathInfo (Join-Path $CanonicalRoot 'app\server.py')),
    (Test-PathInfo (Join-Path $CanonicalRoot 'pythonw.exe')),
    (Test-PathInfo (Join-Path $CanonicalRoot 'python312.zip')),
    (Test-PathInfo 'C:\CAESAR_Vault')
) | Format-Table -AutoSize

Write-Host "`n=== Desktop CAESAR shortcuts ===" -ForegroundColor Cyan
Get-ChildItem -LiteralPath $desktop -Filter '*.lnk' -File -Force |
    Where-Object { $_.Name -match 'CAESAR|Caesar|قيصر|كاشير' } |
    ForEach-Object {
        $s = $ws.CreateShortcut($_.FullName)
        [PSCustomObject]@{
            Shortcut = $_.FullName
            Target = $s.TargetPath
            Arguments = $s.Arguments
            WorkingDirectory = $s.WorkingDirectory
        }
    } | Format-List

Write-Host "`n=== Known runtime roots under the user profile ===" -ForegroundColor Cyan
$roots = @(
    (Join-Path $env:USERPROFILE 'Caesar'),
    'C:\CAESAR_POS',
    'C:\CAESAR',
    'C:\caesar'
) | Select-Object -Unique
$roots | ForEach-Object {
    if (Test-Path -LiteralPath $_) {
        $files = Get-ChildItem -LiteralPath $_ -Recurse -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @('Start.bat','launch.vbs','server.py','CAESAR_POS.exe') } |
            Select-Object -First 20 -ExpandProperty FullName
        [PSCustomObject]@{ Root = $_; Exists = $true; RuntimeFiles = ($files -join ' | ') }
    }
} | Format-List

Write-Host "`n=== Listener and CAESAR processes ===" -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, State, OwningProcess |
    Format-Table -AutoSize
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @('python.exe','pythonw.exe','CAESAR_POS.exe') -or $_.CommandLine -match 'CAESAR|server.py' } |
    Select-Object ProcessId, Name, ExecutablePath, CommandLine |
    Format-List

Write-Host "`n=== License material presence (contents never printed) ===" -ForegroundColor Cyan
$licenseCandidates = @(
    (Join-Path $CanonicalRoot 'app\license_public_key.pem'),
    'C:\CAESAR_Vault\license.json'
)
$licenseCandidates | ForEach-Object {
    $item = Get-Item -LiteralPath $_ -Force -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Path = $_
        Exists = $null -ne $item
        Length = if ($item) { $item.Length } else { 0 }
        Note = if ($_ -match 'public_key') { 'public trust anchor; contents not printed' } else { 'local license metadata only; contents not printed' }
    }
} | Format-Table -AutoSize

if ($IncludeAllUserFiles) {
    Write-Host "`n=== Optional broad search (names only) ===" -ForegroundColor Yellow
    Get-ChildItem -LiteralPath $env:USERPROFILE -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('Start.bat','launch.vbs','CAESAR_POS.exe','generate_license.py','create_vendor_keys.py') } |
        Select-Object FullName, Length, LastWriteTime |
        Sort-Object FullName |
        Format-Table -AutoSize
}

Write-Host "`nDiagnostic complete. Do not paste secret contents or license keys into tickets/GitHub." -ForegroundColor Green
