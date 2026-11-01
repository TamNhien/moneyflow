#Requires -Version 5.1
param([string] $Repository = 'moneyflow')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if ($Repository -notmatch '^[a-zA-Z0-9_.-]+$') { throw 'Repository name is invalid (e.g. moneyflow).' }
foreach ($tool in @('git','gh')) { if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw ('Install ' + $tool + ' first.') } }
& gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Run: gh auth login' }
& git rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'git init failed.' }
}
$origins = @(& git remote)
if ($origins -contains 'origin') {
    Write-Host 'origin already exists. No new repository created.' -ForegroundColor Yellow
    & git remote -v
    exit 0
}
Write-Host 'Creating a PRIVATE GitHub repository (no automatic push in setup)...' -ForegroundColor Cyan
& gh repo create $Repository --private --source . --remote origin
if ($LASTEXITCODE -ne 0) { throw 'Repository creation failed; check account permissions and name.' }
Write-Host 'Connected origin. Next use: .\scripts\publish.ps1 -Version 1.0.4' -ForegroundColor Green
