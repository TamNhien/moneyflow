#Requires -Version 5.1
param([string] $Version = '1.0.14')
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^v?\d+\.\d+\.\d+$') { throw 'Version format: 1.0.4 or v1.0.4' }
$Version = $Version.TrimStart('v')
$checkedVersion = (Get-Content (Join-Path (Split-Path -Parent $PSScriptRoot) 'VERSION') -Raw).Trim()
if ($checkedVersion -ne $Version) { throw ('VERSION file does not match requested release: ' + $checkedVersion + ' != ' + $Version) }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$dist = Join-Path $root 'dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$baseName = 'MoneyFlow-Local-v' + $Version + '-Full-Source.zip'
$zipPath = Join-Path $dist $baseName
$stage = Join-Path ([IO.Path]::GetTempPath()) ('moneyflow-release-' + [guid]::NewGuid().ToString('N'))
$source = Join-Path $stage 'moneyflow'
$files = @('.gitignore','.dockerignore','.env.example','Dockerfile','Dockerfile.test','docker-compose.yml','Caddyfile','README.md','VERSION')
$folders = @('backend','frontend','scripts','tests','.github','preview')
$excluded = '(?i)(^|[\\/])(__pycache__|\.pytest_cache|\.git|backups?|dist|node_modules|\.venv|venv|\.mypy_cache)([\\/]|$)|(^|[\\/])\.env$|\.(pyc|db|sqlite|sqlite3|dump|sqlitedb|log|pem|key|p12|pfx|zip)$'
try {
    New-Item -ItemType Directory -Path $source -Force | Out-Null
    foreach ($file in $files) {
        $full = Join-Path $root $file
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw ('Missing package file: ' + $file) }
        Copy-Item -LiteralPath $full -Destination (Join-Path $source $file) -Force
    }
    foreach ($folder in $folders) {
        $folderPath = Join-Path $root $folder
        if (-not (Test-Path -LiteralPath $folderPath -PathType Container)) { throw ('Missing package folder: ' + $folder) }
        Get-ChildItem -LiteralPath $folderPath -File -Recurse | ForEach-Object {
            $relative = $_.FullName.Substring($root.Length).TrimStart([char]'\',[char]'/')
            if ($relative -match $excluded) { return }
            $target = Join-Path $source $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
    $copied = @(Get-ChildItem -LiteralPath $source -File -Recurse)
    if ($copied.Count -lt 15) { throw 'Suspiciously small package; packaging aborted.' }
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -LiteralPath $source -DestinationPath $zipPath -CompressionLevel Optimal
    $sha = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashPath = $zipPath + '.sha256'
    [IO.File]::WriteAllText($hashPath, ($sha + '  ' + $baseName + "`n"), (New-Object Text.UTF8Encoding($false)))
    Write-Host ('Source ZIP: ' + $zipPath) -ForegroundColor Green
    Write-Host ('SHA-256:    ' + $hashPath) -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
