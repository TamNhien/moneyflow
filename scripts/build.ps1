#Requires -Version 5.1
param([string] $Version = '1.0.11')
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version format: 1.0.4' }
Set-Location (Split-Path -Parent $PSScriptRoot)
& (Join-Path $PSScriptRoot 'ensure-docker.ps1')
if (-not $?) { throw 'Docker Engine chua san sang.' }
$tag = 'moneyflow-local-app:v' + $Version
Write-Host ('Building ' + $tag) -ForegroundColor Cyan
& docker build -t $tag .
if ($LASTEXITCODE -ne 0) { throw 'Docker app build failed.' }
Write-Host ('Built image ' + $tag) -ForegroundColor Green
