$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Chua cai Docker Desktop hoac Docker chua nam trong PATH.' }
if (-not (Test-Path .\.env)) {
    [IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), "DB_PASSWORD=moneyflow`n", (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Da tao .env voi mat khau PostgreSQL theo cau hinh local.' -ForegroundColor Green
}

docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose khoi dong that bai. Xem: docker compose logs -f' }
docker compose ps
Write-Host 'Mo MoneyFlow tai http://127.0.0.1:8765' -ForegroundColor Green
Start-Process 'http://127.0.0.1:8765'
