[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$AppDir
)

$ErrorActionPreference = 'Stop'

$appPath = [System.IO.Path]::GetFullPath($AppDir)
$rootPath = Split-Path -Path $appPath -Parent
$exeCandidates = @(
    # launch.vbs starts Start.bat hidden and therefore avoids a console flash.
    # It also guarantees that the current source files are used.
    (Join-Path -Path $rootPath -ChildPath 'launch.vbs')
)
$target = $exeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$icon = Join-Path -Path $appPath -ChildPath 'caesar_icon.ico'

if (-not $target) {
    throw "Application launcher not found: $target"
}

$desktopCandidates = @(
    [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop),
    $(if ($env:OneDrive) { Join-Path -Path $env:OneDrive -ChildPath 'Desktop' }),
    $(if ($env:OneDriveConsumer) { Join-Path -Path $env:OneDriveConsumer -ChildPath 'Desktop' }),
    $(if ($env:OneDriveCommercial) { Join-Path -Path $env:OneDriveCommercial -ChildPath 'Desktop' }),
    $(if ($env:USERPROFILE) { Join-Path -Path $env:USERPROFILE -ChildPath 'Desktop' })
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique

if (-not $desktopCandidates -or $desktopCandidates.Count -eq 0) {
    throw 'Windows Desktop folder was not found for the current user.'
}

$desktop = $desktopCandidates[0]
$shortcutPath = Join-Path -Path $desktop -ChildPath 'CAESAR POS.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $rootPath
$shortcut.Description = 'CAESAR POS offline point of sale'
if (Test-Path -LiteralPath $icon -PathType Leaf) {
    $shortcut.IconLocation = "$icon,0"
} else {
    $shortcut.IconLocation = "$target,0"
}
$shortcut.Save()

if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "Shortcut creation failed: $shortcutPath"
}

Write-Output "Shortcut created successfully: $shortcutPath"
