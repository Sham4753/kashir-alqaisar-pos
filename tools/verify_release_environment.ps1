$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Vault = 'C:\CAESAR_Vault'

Write-Host '=== CAESAR release environment ===' -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host "Vault:   $Vault"

$secretCandidates = @(
    (Join-Path $Root '.license_secret'),
    (Join-Path $Root 'app\.license_secret'),
    (Join-Path $Root 'license.secret'),
    (Join-Path $Root 'app\license.secret')
)
$secret = $secretCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $secret) { throw 'LICENSE_SECRET_MISSING: place the authorized local secret in the project root or app folder; never commit it.' }
Write-Host "License secret: found ($secret)" -ForegroundColor Green

foreach ($required in @('license.json','caesar.sqlite3','data.json')) {
    $path = Join-Path $Vault $required
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "VAULT_FILE_MISSING: $path" }
    Write-Host "Vault file:     $required" -ForegroundColor Green
}

$port = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($port) { Write-Warning 'Port 8080 is currently in use. Stop the running CAESAR instance before updating/building.' }
else { Write-Host 'Port 8080:      available' -ForegroundColor Green }

Write-Host 'Pre-build checks passed. Test Start.bat and verify license/invoices before building the EXE.' -ForegroundColor Green
