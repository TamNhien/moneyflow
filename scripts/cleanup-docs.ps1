#Requires -Version 5.1
# Run once after extracting the patch to consolidate old release guides.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
foreach ($filename in @('CHANGELOG.md', 'UPGRADE-TO-v1.0.1.md', 'UPGRADE-TO-v1.0.2.md', 'UPGRADE-TO-v1.0.3.md')) {
    $path = Join-Path $root $filename
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
        Write-Host ('Removed superseded documentation: ' + $filename)
    }
}
Write-Host 'All documentation is consolidated in README.md.' -ForegroundColor Green
