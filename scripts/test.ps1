#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& (Join-Path $PSScriptRoot 'ensure-docker.ps1')
if (-not $?) { throw 'Docker Engine chua san sang.' }
Write-Host '[1/3] Build isolated test image...' -ForegroundColor Cyan
& docker build -f Dockerfile.test -t moneyflow-local-test:latest .
if ($LASTEXITCODE -ne 0) { throw 'Test image build failed.' }
Write-Host '[2/3] Run API unit tests (SQLite temporary, no PostgreSQL volume accessed)...' -ForegroundColor Cyan
& docker run --rm --network none moneyflow-local-test:latest
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; publishing must stop.' }
Write-Host '[3/3] Check frontend JavaScript (when Node.js is installed)...' -ForegroundColor Cyan
if (Get-Command node -ErrorAction SilentlyContinue) {
    & node --check frontend/app.js
    if ($LASTEXITCODE -ne 0) { throw 'Frontend JavaScript syntax invalid.' }
} else {
    Write-Host 'Node.js not installed; JavaScript syntax check skipped locally (CI runs it).' -ForegroundColor Yellow
}
Write-Host 'All available tests passed.' -ForegroundColor Green
