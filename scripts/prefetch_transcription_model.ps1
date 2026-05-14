<#
.SYNOPSIS
  Pre-download and load the faster-whisper transcription model (Windows PowerShell version).
#>

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$PythonBin = "$RepoRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonBin)) {
    Write-Error "Missing $PythonBin. Run:`n  python -m venv .venv`n  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$env:PYTHONPATH = if ($env:PYTHONPATH) { "$RepoRoot;$env:PYTHONPATH" } else { $RepoRoot }

$modelName   = if ($env:TRANSCRIPTION_WARMUP_MODEL)        { $env:TRANSCRIPTION_WARMUP_MODEL }        else { 'small' }
$computeType = if ($env:TRANSCRIPTION_WARMUP_COMPUTE_TYPE) { $env:TRANSCRIPTION_WARMUP_COMPUTE_TYPE } else { 'int8' }

Write-Host "Prefetching faster-whisper model=$modelName compute_type=$computeType"

$script = @"
import os, sys
from services.transcription.service import warmup_model
model_name = os.getenv('TRANSCRIPTION_WARMUP_MODEL', 'small')
compute_type = os.getenv('TRANSCRIPTION_WARMUP_COMPUTE_TYPE', 'int8')
ok, error = warmup_model(model_name=model_name, compute_type=compute_type)
if not ok:
    print(f'Prefetch failed for model={model_name} compute_type={compute_type}: {error}')
    sys.exit(1)
print(f'Prefetch complete for model={model_name} compute_type={compute_type}')
"@

$script | & $PythonBin -
exit $LASTEXITCODE
