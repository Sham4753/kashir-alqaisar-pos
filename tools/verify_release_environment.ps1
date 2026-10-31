[CmdletBinding()]
param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($ProjectRoot)
$Python = Join-Path $Root 'python.exe'
$SitePackages = Join-Path $Root 'Lib\site-packages'
$PublicKey = Join-Path $Root 'app\license_public_key.pem'
$Vault = 'C:\CAESAR_Vault'

Write-Host '=== CAESAR POS Ed25519 release environment ===' -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host "Vault path (must stay outside Git): $Vault"

foreach ($required in @($Python, (Join-Path $Root 'python312.dll'), (Join-Path $Root 'python312.zip'), (Join-Path $Root 'embedded_packages_manifest.json'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "RUNTIME_FILE_MISSING: $required" }
}
$CffiBackend = Get-ChildItem -LiteralPath $SitePackages -Filter '_cffi_backend*.pyd' -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $CffiBackend) { throw 'CFFI_BACKEND_MISSING: expected a Windows CPython 3.12 native backend.' }

if (-not (Test-Path -LiteralPath $PublicKey -PathType Leaf)) {
    throw 'LICENSE_PUBLIC_KEY_MISSING: create the vendor key pair and keep only the public key in app\license_public_key.pem.'
}
$env:PYTHONPATH = "$SitePackages;$Root\app;$Root"
$probe = "import sys; from pathlib import Path; import _cffi_backend; from cryptography.hazmat.primitives import serialization; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey; key=serialization.load_pem_public_key(Path(sys.argv[1]).read_bytes()); assert isinstance(key, Ed25519PublicKey); print('CFFI and Ed25519 runtime ready')"
& $Python -c $probe $PublicKey
if ($LASTEXITCODE -ne 0) { throw 'LICENSE_PUBLIC_KEY_INVALID: runtime import or Ed25519 public-key validation failed.' }

$privateFiles = Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' -and $_.Name -match '(?i)(private|secret).*\.(pem|key|p12|pfx)$' }
if ($privateFiles) { throw 'VENDOR_PRIVATE_KEY_FOUND_IN_REPOSITORY: keep signing keys outside Git; no file contents were inspected.' }

$port = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($port) { Write-Warning 'Port 8080 is currently in use. Stop the running CAESAR instance before testing/building.' }
else { Write-Host 'Port 8080: available' -ForegroundColor Green }

Write-Host 'Release prerequisites passed. Run tests, build on Windows, and inspect the generated ZIPs before distribution.' -ForegroundColor Green
