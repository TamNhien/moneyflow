#Requires -Version 5.1
[CmdletBinding()]
param(
    [string] $Version = '',
    [ValidateRange(30, 7200)][int] $TimeoutSeconds = 1200,
    [ValidateRange(3, 120)][int] $PollSeconds = 10,
    [switch] $NoPopup
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-GhJson {
    param([string[]] $Arguments)
    $raw = & gh @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ('GitHub CLI failed: gh ' + ($Arguments -join ' ') + ' - ' + ($raw -join ' '))
    }
    $content = ($raw -join "`n").Trim()
    if (-not $content) { throw ('Empty response from gh ' + ($Arguments -join ' ')) }
    return (ConvertFrom-Json -InputObject $content)
}

function Show-ReleasePopup {
    param([string] $Message)
    if ($NoPopup -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::UserInteractive) { return }
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [void][System.Windows.Forms.MessageBox]::Show(
            $Message,
            'MoneyFlow - GitHub Release',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        )
    } catch {
        Write-Warning ('Khong hien duoc popup Windows; xem thong bao trong PowerShell: ' + $_.Exception.Message)
    }
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'GitHub CLI (gh) not found.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git (git) not found.' }
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim() }
$Version = $Version.TrimStart('v')
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version must be in format 1.0.10.' }
$tag = 'v' + $Version
$sha = (& git rev-list -n 1 $tag 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $sha) { throw ('Cannot find local Git tag: ' + $tag) }
$sha = ($sha | Select-Object -First 1).Trim()
$repo = (& gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>&1)
if ($LASTEXITCODE -ne 0 -or -not $repo) { throw 'Cannot determine GitHub repository from origin. Check gh auth status and git remote -v.' }
$repo = ($repo | Select-Object -First 1).Trim()
$expectedZip = 'MoneyFlow-Local-' + $tag + '-Full-Source.zip'
$expectedSha = $expectedZip + '.sha256'
$actionsUrl = 'https://github.com/' + $repo + '/actions/workflows/release.yml'
Write-Host ('Checking automatic Release ' + $tag + ' in ' + $repo) -ForegroundColor Cyan
Write-Host ('Expected assets: ' + $expectedZip + ', ' + $expectedSha) -ForegroundColor DarkGray

$clock = [Diagnostics.Stopwatch]::StartNew()
$runId = 0
$runUrl = $actionsUrl
$lastState = ''
$apiFailures = 0
$releaseFailures = 0
$release = $null
while ($clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    try {
        # Restrict the run to the exact commit, workflow, push event AND tag.
        # Checking only "latest" can report an unrelated successful release.
        $runs = @(Invoke-GhJson -Arguments @('run', 'list', '-R', $repo, '--workflow', 'release.yml', '--event', 'push', '--commit', $sha, '--limit', '50', '--json', 'databaseId,headBranch,headSha,status,conclusion,url,event'))
        $match = @($runs | Where-Object { $_.headBranch -eq $tag -and $_.headSha -eq $sha -and $_.event -eq 'push' } | Sort-Object -Property databaseId -Descending | Select-Object -First 1)
        $apiFailures = 0
    } catch {
        $apiFailures++
        if ($apiFailures -ge 3) { throw ('Cannot query GitHub Actions after 3 attempts: ' + $_.Exception.Message) }
        Write-Warning ('Cannot query GitHub Actions (' + $apiFailures + '/3); retrying: ' + $_.Exception.Message)
        Start-Sleep -Seconds $PollSeconds
        continue
    }
    if ($match.Count -eq 0) {
        $state = 'Waiting for tagged GitHub Actions workflow to appear...'
    } else {
        $run = $match[0]
        $runId = $run.databaseId
        $runUrl = $run.url
        $state = 'GitHub Actions run #' + $runId + ': ' + $run.status + ' / ' + $run.conclusion
        if ($run.status -eq 'completed' -and $run.conclusion -ne 'success') {
            throw ('RELEASE FAILED: GitHub Actions finished with ' + $run.conclusion + '. See: ' + $runUrl)
        }
        if ($run.status -eq 'completed' -and $run.conclusion -eq 'success') {
            # GH Actions success alone is insufficient: verify the published Release and both uploaded assets.
            try {
                $release = Invoke-GhJson -Arguments @('release', 'view', $tag, '-R', $repo, '--json', 'tagName,isDraft,publishedAt,url,assets')
                $releaseFailures = 0
            } catch {
                $release = $null
                $releaseFailures++
                if ($releaseFailures -ge 3) { throw ('GitHub Actions passed, but Release could not be queried: ' + $_.Exception.Message) }
            }
            if ($null -ne $release -and $release.tagName -eq $tag -and -not $release.isDraft -and $release.publishedAt) {
                $assets = @($release.assets)
                $zip = @($assets | Where-Object { $_.name -eq $expectedZip -and $_.size -gt 0 })
                $shaFile = @($assets | Where-Object { $_.name -eq $expectedSha -and $_.size -gt 0 })
                if ($zip.Count -gt 0 -and $shaFile.Count -gt 0) {
                    Write-Host ''
                    Write-Host '=====================================================' -ForegroundColor Green
                    Write-Host (' GITHUB RELEASE ' + $tag + ' CREATED SUCCESSFULLY!') -ForegroundColor Green
                    Write-Host ' Workflow: SUCCESS | Release: PUBLISHED | Assets: 2/2' -ForegroundColor Green
                    Write-Host '=====================================================' -ForegroundColor Green
                    Write-Host ('Release URL: ' + $release.url) -ForegroundColor Cyan
                    Write-Host ('Actions URL: ' + $runUrl) -ForegroundColor Cyan
                    Show-ReleasePopup ('MoneyFlow ' + $tag + " da tao GitHub Release thanh cong!`r`n" +
                        "GitHub Actions: SUCCESS`r`nRelease: PUBLISHED`r`nZIP + SHA-256: DA XAC NHAN`r`n`r`n" + $release.url)
                    return
                }
                $state = 'Release published; waiting for both ZIP and SHA-256 assets...'
            } else {
                $state = 'Workflow succeeded; waiting for published Release...'
            }
        }
    }
    if ($state -ne $lastState) {
        Write-Host ('[' + [int]$clock.Elapsed.TotalSeconds + 's] ' + $state) -ForegroundColor Yellow
        $lastState = $state
    }
    Start-Sleep -Seconds $PollSeconds
}
throw ('RELEASE NOT CONFIRMED after ' + $TimeoutSeconds + ' seconds. No success notification issued. Check: ' + $runUrl + ' and https://github.com/' + $repo + '/releases/tag/' + $tag)
