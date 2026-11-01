#Requires -Version 5.1
param([string] $Version = '1.0.4')
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version format: 1.0.4' }
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker is missing.' }
& docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Engine is not running.' }
$tag = 'moneyflow-local-app:v' + $Version
Write-Host ('Building ' + $tag) -ForegroundColor Cyan
& docker build -t $tag .
if ($LASTEXITCODE -ne 0) { throw 'Docker app build failed.' }
Write-Host ('Built image ' + $tag) -ForegroundColor Green
