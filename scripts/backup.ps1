$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path .\backups | Out-Null
$containerId = (docker compose ps -q db).Trim()
if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'PostgreSQL chua chay. Hay chay scripts/start.ps1 truoc.' }
$name = 'moneyflow-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
$tmp = '/tmp/' + $name
try {
    docker compose exec -T db pg_dump -U moneyflow -d moneyflow -Fc -f $tmp
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump that bai.' }
    docker cp "${containerId}:$tmp" (Join-Path (Get-Location) ('backups\' + $name))
    if ($LASTEXITCODE -ne 0) { throw 'docker cp that bai.' }
    Write-Host ('Sao luu thanh cong: backups\' + $name) -ForegroundColor Green
} finally {
    docker compose exec -T db rm -f $tmp | Out-Null
}
