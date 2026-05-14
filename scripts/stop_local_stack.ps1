<#
.SYNOPSIS
  Stop processes started by scripts\start_local_stack.ps1 (-Detach or leftover PIDs).
#>

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidsFile = "$RepoRoot\.run\local_stack.pids"

if (-not (Test-Path $PidsFile)) {
    Write-Host "No $PidsFile — nothing to stop (or stack was not started via start_local_stack.ps1)."
    exit 0
}

Get-Content $PidsFile | ForEach-Object {
    $procId = [int]$_.Trim()
    if ($procId) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "Stopped pid $procId"
        } catch {
            Write-Host "pid $procId already gone"
        }
    }
}

Remove-Item $PidsFile -ErrorAction SilentlyContinue
Write-Host "Done."
