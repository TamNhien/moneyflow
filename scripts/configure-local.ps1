$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

# Apply AFTER copying v1.0.1 files into the existing project folder.
# The PostgreSQL container is recreated on host port 5435; its internal port stays 5432.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop chua cai dat hoac Docker khong co trong PATH.'
}
$envPath = Join-Path (Get-Location) '.env'
if (-not (Test-Path $envPath)) {
    [IO.File]::WriteAllText($envPath, "DB_PASSWORD=moneyflow`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Da tao .env cho cai dat moi.' -ForegroundColor Yellow
}

Write-Host 'Dang khoi dong PostgreSQL tai 127.0.0.1:5435 ...' -ForegroundColor Cyan
docker compose up -d db
if ($LASTEXITCODE -ne 0) { throw 'Khong the khoi dong db. Kiem tra cong 5435 va docker compose logs db.' }

# POSTGRES_PASSWORD in Compose does not update a password already stored in a Postgres data volume.
# A local Unix socket psql command changes the existing moneyflow role inside its own database.
Write-Host 'Dong bo mat khau database user moneyflow ...' -ForegroundColor Cyan
docker compose exec -T db psql -U moneyflow -d moneyflow -v ON_ERROR_STOP=1 -c "ALTER ROLE moneyflow WITH PASSWORD 'moneyflow';"
if ($LASTEXITCODE -ne 0) { throw 'Khong the doi mat khau role moneyflow. .env hien tai CHUA BI THAY DOI.' }

# Preserve unrelated .env entries instead of clobbering custom settings.
$existing = [IO.File]::ReadAllText($envPath)
if ($existing -match '(?m)^DB_PASSWORD=') {
    $next = [regex]::Replace($existing, '(?m)^DB_PASSWORD=.*$', 'DB_PASSWORD=moneyflow')
} else {
    $next = $existing.TrimEnd("`r", "`n") + "`nDB_PASSWORD=moneyflow`n"
}
[IO.File]::WriteAllText($envPath, $next, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'Da cap nhat .env. Dang khoi dong lai ung dung ...' -ForegroundColor Cyan
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Khong the khoi dong app. Kiem tra docker compose logs --tail=100 app.' }

docker compose ps
Write-Host 'MoneyFlow: https://127.0.0.1:8765' -ForegroundColor Green
Write-Host 'pgAdmin: 127.0.0.1:5435, DB moneyflow, user moneyflow, password moneyflow' -ForegroundColor Green
