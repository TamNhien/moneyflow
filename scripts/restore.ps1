param([Parameter(Mandatory=$true)][string]$BackupFile)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$fullPath = (Resolve-Path $BackupFile).Path
if (-not (Test-Path $fullPath)) { throw 'Khong tim thay file backup.' }
Write-Host 'CANH BAO: Phuc hoi se THAY THE du lieu hien tai.' -ForegroundColor Yellow
$confirm = Read-Host 'Nhap PHUC HOI de tiep tuc'
if ($confirm -cne 'PHUC HOI') { Write-Host 'Da huy.'; exit }
$containerId = (docker compose ps -q db).Trim()
if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'PostgreSQL chua chay.' }
docker compose stop app
if ($LASTEXITCODE -ne 0) { throw 'Khong the dung app.' }
try {
    docker cp $fullPath "${containerId}:/tmp/moneyflow-restore.dump"
    if ($LASTEXITCODE -ne 0) { throw 'Khong the chuyen file backup.' }
    docker compose exec -T db pg_restore -U moneyflow -d moneyflow --clean --if-exists --no-owner /tmp/moneyflow-restore.dump
    if ($LASTEXITCODE -ne 0) { throw 'Phuc hoi that bai. Can kiem tra du lieu truoc khi chay lai.' }
    Write-Host 'Phuc hoi thanh cong.' -ForegroundColor Green
} finally {
    docker compose exec -T db rm -f /tmp/moneyflow-restore.dump | Out-Null
    docker compose start app
}
