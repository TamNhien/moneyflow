$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& (Join-Path $PSScriptRoot 'ensure-docker.ps1')
if (-not $?) { throw 'Docker Engine chua san sang.' }
if (-not (Test-Path .\.env)) {
    [IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), "DB_PASSWORD=moneyflow`n", (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Da tao .env voi mat khau PostgreSQL theo cau hinh local.' -ForegroundColor Green
}

& docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose khoi dong that bai. Xem: docker compose logs -f' }
docker compose ps
Write-Host 'Mo MoneyFlow tai https://127.0.0.1:8765' -ForegroundColor Green
Write-Host 'Neu lan dau su dung HTTPS, chay: .\scripts\trust-local-https.ps1' -ForegroundColor Yellow
