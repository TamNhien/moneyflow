#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateRange(15,900)]
    [int] $DockerTimeoutSeconds = 180
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host '[1/3] Kiem tra/tu dong mo Docker Desktop...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'ensure-docker.ps1') -TimeoutSeconds $DockerTimeoutSeconds
if (-not $?) { throw 'Docker Engine chua san sang.' }
Write-Host '[2/3] Kiem thu MoneyFlow...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'test.ps1')
if (-not $?) { throw 'Test that bai, khong khoi dong ung dung.' }
Write-Host '[3/3] Build va chay MoneyFlow...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'start.ps1')
if (-not $?) { throw 'Khong khoi dong duoc MoneyFlow.' }
