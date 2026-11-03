$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& (Join-Path $PSScriptRoot 'ensure-docker.ps1')
if (-not $?) { throw 'Docker Engine chua san sang.' }
if (-not (Test-Path .\.env)) {
    [IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), "DB_PASSWORD=moneyflow`n", (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Da tao .env voi mat khau PostgreSQL theo cau hinh local.' -ForegroundColor Green
}

# Generate a persistent, per-installation Fernet key for encrypted TOTP secrets.
# Do not regenerate this key on subsequent launches or users will lose 2FA access.
$envPath = Join-Path (Get-Location) '.env'
$envLines = [IO.File]::ReadAllText($envPath)
if ($envLines -notmatch '(?m)^TOTP_ENCRYPTION_KEY=\S+') {
    if ($envLines -match '(?m)^TOTP_ENCRYPTION_KEY=') {
        throw 'TOTP_ENCRYPTION_KEY is blank. Check .env: do not replace an existing key if 2FA was enabled.'
    }
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $key = [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_')
    [IO.File]::AppendAllText($envPath, "`nTOTP_ENCRYPTION_KEY=$key`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'TOTP encryption key generated in local .env.' -ForegroundColor Green
}

& docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose khoi dong that bai. Xem: docker compose logs -f' }
docker compose ps
Write-Host 'Mo MoneyFlow tai https://127.0.0.1:8765' -ForegroundColor Green
Write-Host 'Neu lan dau su dung HTTPS, chay: .\scripts\trust-local-https.ps1' -ForegroundColor Yellow
