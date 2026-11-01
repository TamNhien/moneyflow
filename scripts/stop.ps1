$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose stop
if ($LASTEXITCODE -ne 0) { throw 'Khong the dung Docker Compose.' }
Write-Host 'Da dung MoneyFlow. Du lieu PostgreSQL van duoc giu lai.' -ForegroundColor Green
