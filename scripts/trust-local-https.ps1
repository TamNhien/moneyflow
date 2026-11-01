#Requires -Version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop is not available.' }
$idLines = @(& docker compose ps -q caddy)
if ($LASTEXITCODE -ne 0 -or $idLines.Count -eq 0 -or -not ($idLines[0].Trim())) { throw 'Start Caddy first: docker compose up -d --build' }
$containerId = $idLines[0].Trim()
$tempCert = Join-Path ([IO.Path]::GetTempPath()) ('moneyflow-root-' + [guid]::NewGuid().ToString('N') + '.crt')
try {
    $source = "${containerId}:/data/caddy/pki/authorities/local/root.crt"
    $copied = $false
    for ($attempt=0; $attempt -lt 15; $attempt++) {
        & docker cp $source $tempCert 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $tempCert)) { $copied = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $copied) { throw 'Caddy local CA is not ready. Check docker compose logs caddy.' }
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($tempCert)
    if ($cert.Subject -notmatch 'Caddy|Local') { throw ('Unexpected CA certificate subject: ' + $cert.Subject) }
    Write-Host ('CA Subject: ' + $cert.Subject) -ForegroundColor Cyan
    Write-Host ('CA SHA1 thumbprint: ' + $cert.Thumbprint) -ForegroundColor Cyan
    Write-Warning 'Installing a root CA grants it authority to issue trusted TLS certificates for this Windows user. Only do this for your own trusted MoneyFlow installation.'
    $answer = Read-Host 'Do you trust this Caddy local CA? Type YES to install in CurrentUser\Root'
    if ($answer -cne 'YES') { Write-Host 'Cancelled; no certificate installed.'; return }
    Import-Certificate -FilePath $tempCert -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
    Write-Host 'CA installed for current Windows user. Open https://127.0.0.1:8765' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $tempCert) { Remove-Item -LiteralPath $tempCert -Force }
}
