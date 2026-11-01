#Requires -Version 5.1
[CmdletBinding()]
param(
    [string] $Version = '',
    [ValidateSet('patch', 'minor', 'major')][string] $Bump = 'patch'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked([string] $Program, [string[]] $Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw ("Command failed: " + $Program + " " + ($Arguments -join ' ')) }
}
function New-NextVersion([string] $Current, [string] $Kind) {
    if ($Current -notmatch '^(\d+)\.(\d+)\.(\d+)$') { throw ('Invalid VERSION file: ' + $Current) }
    $major = [int]$Matches[1]; $minor = [int]$Matches[2]; $patch = [int]$Matches[3]
    switch ($Kind) {
        'major' { return ('{0}.0.0' -f ($major + 1)) }
        'minor' { return ('{0}.{1}.0' -f $major, ($minor + 1)) }
        'patch' { return ('{0}.{1}.{2}' -f $major, $minor, ($patch + 1)) }
    }
}

foreach ($tool in @('git', 'gh', 'docker')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw ('Required program not found: ' + $tool) }
}
$versionFile = Join-Path $root 'VERSION'
if (-not (Test-Path -LiteralPath $versionFile)) { throw 'Missing VERSION file.' }
$current = (Get-Content -LiteralPath $versionFile -Raw).Trim()
if (-not $Version) { $Version = New-NextVersion $current $Bump }
$Version = $Version.TrimStart('v')
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Use semantic version: 1.0.4' }
$tag = 'v' + $Version
Write-Host ('Publishing ' + $tag + ' (current VERSION: ' + $current + ')') -ForegroundColor Cyan

Invoke-Checked 'gh' @('auth', 'status')
& git rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Not a Git repository. Run scripts/github-setup.ps1 first.' }
$remotes = @(& git remote)
if ($LASTEXITCODE -ne 0 -or $remotes -notcontains 'origin') { throw 'Git origin not configured. Run scripts/github-setup.ps1.' }
$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or -not $branch) { throw 'Publishing detached HEAD is not supported.' }
if ($branch -ne 'main') { throw ('Switch to main branch before release; currently ' + $branch) }
$tags = @(& git tag -l $tag)
if ($tags.Count -gt 0) { throw ('Release tag exists locally: ' + $tag) }
$remoteTag = @(& git ls-remote --tags origin ('refs/tags/' + $tag))
if ($LASTEXITCODE -ne 0) { throw 'Cannot check remote tags.' }
if ($remoteTag.Count -gt 0) { throw ('Release tag exists on GitHub: ' + $tag) }

# Whitelist only source paths. Obsolete documentation is staged separately as tracked deletions.
# Do not pass nonexistent paths to `git add`, which fails with "pathspec did not match any files".
$allowed = @('.gitignore', '.dockerignore', '.env.example', 'Dockerfile', 'Dockerfile.test',
             'docker-compose.yml', 'README.md', 'VERSION', 'backend', 'frontend',
             'scripts', 'tests', '.github', 'preview')
$legacyDocs = @('CHANGELOG.md', 'UPGRADE-TO-v1.0.1.md',
                'UPGRADE-TO-v1.0.2.md', 'UPGRADE-TO-v1.0.3.md')
Write-Host '[1/6] Isolated API tests and frontend syntax...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'test.ps1')
if (-not $?) { throw 'Tests failed; nothing pushed.' }
Write-Host '[2/6] Build application image...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'build.ps1') -Version $Version
if (-not $?) { throw 'Application build failed; nothing pushed.' }
Write-Host '[3/6] Generate source ZIP and SHA-256...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'cleanup-docs.ps1')
if (-not $?) { throw 'Documentation cleanup failed.' }
# New releases append a concise entry in the single README; edit details before publishing when needed.
if ($Version -ne $current) {
    $readmePath = Join-Path $root 'README.md'
    $readmeBody = Get-Content -LiteralPath $readmePath -Raw
    if ($readmeBody -notmatch ('(?m)^### v' + [regex]::Escape($Version) + '($|:)')) {
        $entry = "`n### v$Version : Release $(Get-Date -Format 'yyyy-MM-dd')`n`n- Source code, tests and build published automatically using the GitHub workflow.`n"
        [IO.File]::AppendAllText($readmePath, $entry, (New-Object Text.UTF8Encoding($false)))
    }
}
[IO.File]::WriteAllText($versionFile, ($Version + "`n"), (New-Object Text.UTF8Encoding($false)))
& (Join-Path $PSScriptRoot 'package.ps1') -Version $Version
if (-not $?) { throw 'Packaging failed; nothing pushed.' }
Write-Host '[4/6] Verify Git staged files (secrets excluded)...' -ForegroundColor Cyan
# Git fails when ANY pathspec does not exist in a new repository. Stage real paths only.
$presentPaths = @($allowed | Where-Object { Test-Path -LiteralPath (Join-Path $root $_) })
if ($presentPaths.Count -eq 0) { throw 'No source files found for Git staging.' }
& git add -A -- $presentPaths
if ($LASTEXITCODE -ne 0) { throw 'git add failed while staging source files.' }

# When upgrading a pre-existing Git repository, record deletions of old guides.
# `git ls-files` returns success and an empty list for untracked/missing legacy docs.
$trackedLegacy = @(& git ls-files -- $legacyDocs)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect tracked legacy documentation.' }
foreach ($oldDoc in $trackedLegacy) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $oldDoc))) {
        & git add -u -- $oldDoc
        if ($LASTEXITCODE -ne 0) { throw ('Unable to stage removal of ' + $oldDoc) }
    }
}
$staged = @(& git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect staged files.' }
foreach ($entry in $staged) {
    $normalized = $entry.Replace('\', '/')
    $top = ($normalized -split '/')[0]
    if ($allowed -notcontains $top -and $legacyDocs -notcontains $normalized) {
        throw ('Unexpected staged path: ' + $entry)
    }
    if ($legacyDocs -contains $normalized -and (Test-Path -LiteralPath (Join-Path $root $normalized))) {
        throw ('Legacy documentation must be deleted before publishing: ' + $entry)
    }
    if ($normalized -match '(^|/)\.env($|\.)|(^|/)(backups?|dist|\.git|\.pytest_cache|__pycache__|\.venv|node_modules)(/|$)|\.(db|sqlite3?|dump|pem|key|p12|pfx|zip|log)$') {
        if ($normalized -ne '.env.example') { throw ('Unsafe staged file: ' + $entry) }
    }
}
if ($staged.Count -eq 0) { throw 'No project changes staged. Make a source or README change before publishing.' }
& git diff --cached --stat
if ($LASTEXITCODE -ne 0) { throw 'Git diff failed.' }
Write-Host '[5/6] Commit and push to GitHub...' -ForegroundColor Cyan
Invoke-Checked 'git' @('commit', '-m', ('release: ' + $tag))
Invoke-Checked 'git' @('push', '-u', 'origin', 'HEAD:main')
Write-Host '[6/6] Create and push annotated version tag...' -ForegroundColor Cyan
Invoke-Checked 'git' @('tag', '-a', $tag, '-m', ('MoneyFlow Local ' + $tag))
Invoke-Checked 'git' @('push', 'origin', $tag)
Write-Host ('Source pushed. GitHub Actions will verify ' + $tag + ' then create a GitHub Release.') -ForegroundColor Green
Write-Host 'Repository > Actions: CI / Release; Repository > Releases: assets.' -ForegroundColor Cyan
