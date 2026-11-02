#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateRange(15, 900)]
    [int] $TimeoutSeconds = 180
)
$ErrorActionPreference = 'Stop'

# Check the Docker *server*, not just whether docker.exe is installed.
# ProcessStartInfo keeps expected "daemon not running" stderr out of the terminal.
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    throw 'Khong tim thay docker CLI. Hay cai Docker Desktop cho Windows truoc.'
}
$dockerExe = $dockerCmd.Source

function Test-DockerEngineReady {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $dockerExe
    $psi.Arguments = 'info --format "{{.ServerVersion}}"'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $process = $null
    try {
        $process = [System.Diagnostics.Process]::Start($psi)
        if (-not $process.WaitForExit(5000)) {
            try { $process.Kill() } catch { }
            return $false
        }
        $output = $process.StandardOutput.ReadToEnd().Trim()
        return ($process.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($output))
    } catch {
        return $false
    } finally {
        if ($process) { $process.Dispose() }
    }
}

function Invoke-DockerDesktopStartCli {
    # Docker Desktop >= 4.37 supports `docker desktop start --detach`.
    # An older CLI may reject the option; in that case fall back to the GUI.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $dockerExe
    $psi.Arguments = 'desktop start --detach'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $process = $null
    try {
        $process = [System.Diagnostics.Process]::Start($psi)
        if (-not $process.WaitForExit(15000)) {
            try { $process.Kill() } catch { }
            return $false
        }
        return ($process.ExitCode -eq 0)
    } catch {
        return $false
    } finally {
        if ($process) { $process.Dispose() }
    }
}

if (Test-DockerEngineReady) {
    Write-Host 'Docker Engine da san sang.' -ForegroundColor Green
    return
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Docker Engine chua san sang. Tu khoi dong Docker Desktop chi duoc ho tro tren Windows.'
}

Write-Host 'Docker Engine chua chay. Dang tu dong mo Docker Desktop...' -ForegroundColor Yellow
$started = Invoke-DockerDesktopStartCli
if (-not $started) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path ${env:LOCALAPPDATA} 'Programs\DockerDesktop\Docker Desktop.exe'),
        (Join-Path ${env:LOCALAPPDATA} 'Programs\Docker\Docker Desktop.exe')
    )
    $desktopExe = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
    if (-not $desktopExe) {
        throw 'Khong tim thay Docker Desktop.exe. Kiem tra lai noi cai Docker Desktop. D:\DockerData chi la thu muc luu du lieu.'
    }
    Start-Process -FilePath $desktopExe | Out-Null
    Write-Host 'Da yeu cau mo Docker Desktop tren Windows.' -ForegroundColor Cyan
}

Write-Host ("Dang doi Docker Engine toi da {0} giay ..." -f $TimeoutSeconds) -ForegroundColor Cyan
$timer = [Diagnostics.Stopwatch]::StartNew()
$lastReport = -1
while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    if (Test-DockerEngineReady) {
        Write-Host 'Docker Engine da khoi dong thanh cong.' -ForegroundColor Green
        return
    }
    $elapsed = [int] $timer.Elapsed.TotalSeconds
    if ($elapsed -ge 15 -and [int][math]::Floor($elapsed / 15) -gt $lastReport) {
        $lastReport = [int][math]::Floor($elapsed / 15)
        Write-Host ("Dang doi Docker Engine... {0}s" -f $elapsed) -ForegroundColor DarkGray
    }
    Start-Sleep -Seconds 3
}
throw ("Docker Desktop khong san sang sau {0} giay. Mo Docker Desktop kiem tra thong bao loi, sau do chay 'docker desktop status' va 'wsl --list --verbose'. Khong can xoa Docker volume hay PostgreSQL." -f $TimeoutSeconds)
