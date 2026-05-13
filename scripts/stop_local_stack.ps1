$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidsFile = Join-Path $RepoRoot ".run\local_stack.pids"

if (-not (Test-Path -Path $pidsFile)) {
    Write-Host "No $pidsFile - nothing to stop (or stack was not started via start_local_stack.ps1)."
    exit 0
}

foreach ($pidLine in Get-Content -Path $pidsFile) {
    if ([string]::IsNullOrWhiteSpace($pidLine)) {
        continue
    }

    try {
        Stop-Process -Id ([int]$pidLine) -ErrorAction Stop
        Write-Host ("Stopped pid {0}" -f $pidLine)
    }
    catch {
    }
}

Remove-Item -Path $pidsFile -Force -ErrorAction SilentlyContinue
Write-Host "Done."