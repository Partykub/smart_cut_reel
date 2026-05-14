<#
.SYNOPSIS
  Start all microservices + Orchestrator on localhost (Windows PowerShell version).

.DESCRIPTION
  Vision/reframe stack (8010-8018): validation, media_metadata, proxy_frame_sampling,
    body_detection, track_interpolation, reframe_planning, easing_smoothing,
    render_plan_compiler, ffmpeg_renderer.
  Dead-air chain (8019-8021): audio_extraction, voice_activity_detection, dead_air_cut_planning.
  Audio-quality chain (8022-8023): audio_enhancement, transcription.

  Prerequisites: Python venv with requirements.txt, ffmpeg + ffprobe on PATH, Node (for frontend).

.PARAMETER Detach
  Background everything; logs under .run\logs\

.PARAMETER PrefetchTranscriptionModel
  Pre-download/load faster-whisper model before services boot.

.EXAMPLE
  .\scripts\start_local_stack.ps1
  .\scripts\start_local_stack.ps1 -Detach
  .\scripts\start_local_stack.ps1 -PrefetchTranscriptionModel

  Then in another terminal:
    cd frontend ; npm run dev
  Open http://localhost:3000
#>
param(
    [switch]$Detach,
    [switch]$PrefetchTranscriptionModel
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# ---------------------------------------------------------------------------
# Load .env.local (key=value lines, skips comments and blank lines)
# ---------------------------------------------------------------------------
if (Test-Path "$RepoRoot\.env.local") {
    Get-Content "$RepoRoot\.env.local" | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $key = $Matches[1]
            $val = $Matches[2] -replace '^"(.*)"$', '$1' -replace "^'(.*)'$", '$1'
            if (-not (Get-Item "Env:$key" -ErrorAction SilentlyContinue)) {
                Set-Item "Env:$key" $val
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
$Uvicorn = "$RepoRoot\.venv\Scripts\uvicorn.exe"
if (-not (Test-Path $Uvicorn)) {
    Write-Error "Missing $Uvicorn. Run:`n  python -m venv .venv`n  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

foreach ($cmd in @('ffmpeg', 'ffprobe')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Missing '$cmd' on PATH (required for media_metadata / proxy / renderer / audio_extraction)."
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$RepoRoot;$env:PYTHONPATH" } else { $RepoRoot }

if (-not $env:SMART_CUT_OBJECT_STORE_ROOT) {
    $env:SMART_CUT_OBJECT_STORE_ROOT = "$RepoRoot\.orchestrator-data"
}
New-Item -ItemType Directory -Force -Path $env:SMART_CUT_OBJECT_STORE_ROOT | Out-Null

$RunDir = "$RepoRoot\.run"
New-Item -ItemType Directory -Force -Path "$RunDir\logs" | Out-Null

if (-not $env:ORCHESTRATOR_MINIO_BUCKET) { $env:ORCHESTRATOR_MINIO_BUCKET = 'smart-cut' }

$Base = if ($env:LOCAL_STACK_HOST) { $env:LOCAL_STACK_HOST } else { '127.0.0.1' }

# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
$P_VALIDATION   = if ($env:VALIDATION_PORT)               { $env:VALIDATION_PORT }               else { '8010' }
$P_META         = if ($env:MEDIA_METADATA_PORT)           { $env:MEDIA_METADATA_PORT }           else { '8011' }
$P_PROXY        = if ($env:PROXY_FRAME_SAMPLING_PORT)     { $env:PROXY_FRAME_SAMPLING_PORT }     else { '8012' }
$P_BODY         = if ($env:BODY_DETECTION_PORT)           { $env:BODY_DETECTION_PORT }           else { '8013' }
$P_TRACK        = if ($env:TRACK_INTERPOLATION_PORT)      { $env:TRACK_INTERPOLATION_PORT }      else { '8014' }
$P_REFRAME      = if ($env:REFRAME_PLANNING_PORT)         { $env:REFRAME_PLANNING_PORT }         else { '8015' }
$P_EASING       = if ($env:EASING_SMOOTHING_PORT)         { $env:EASING_SMOOTHING_PORT }         else { '8016' }
$P_COMPILER     = if ($env:RENDER_PLAN_COMPILER_PORT)     { $env:RENDER_PLAN_COMPILER_PORT }     else { '8017' }
$P_FFMPEG       = if ($env:FFMPEG_RENDERER_PORT)          { $env:FFMPEG_RENDERER_PORT }          else { '8018' }
$P_AUDIO        = if ($env:AUDIO_EXTRACTION_PORT)         { $env:AUDIO_EXTRACTION_PORT }         else { '8019' }
$P_VAD          = if ($env:VOICE_ACTIVITY_DETECTION_PORT) { $env:VOICE_ACTIVITY_DETECTION_PORT } else { '8020' }
$P_CUT_PLAN     = if ($env:DEAD_AIR_CUT_PLANNING_PORT)    { $env:DEAD_AIR_CUT_PLANNING_PORT }    else { '8021' }
$P_AUDIO_ENHANCE= if ($env:AUDIO_ENHANCEMENT_PORT)        { $env:AUDIO_ENHANCEMENT_PORT }        else { '8022' }
$P_TRANSCRIPTION= if ($env:TRANSCRIPTION_PORT)            { $env:TRANSCRIPTION_PORT }            else { '8023' }
$P_ORCH         = if ($env:ORCHESTRATOR_PORT)             { $env:ORCHESTRATOR_PORT }             else { '8000' }

# ---------------------------------------------------------------------------
# Build ORCHESTRATOR_SERVICE_ENDPOINTS JSON
# ---------------------------------------------------------------------------
$endpoints = [ordered]@{
    validation               = "http://${Base}:${P_VALIDATION}"
    media_metadata           = "http://${Base}:${P_META}"
    proxy_frame_sampling     = "http://${Base}:${P_PROXY}"
    body_detection           = "http://${Base}:${P_BODY}"
    track_interpolation      = "http://${Base}:${P_TRACK}"
    reframe_planning         = "http://${Base}:${P_REFRAME}"
    easing_smoothing         = "http://${Base}:${P_EASING}"
    render_plan_compiler     = "http://${Base}:${P_COMPILER}"
    ffmpeg_renderer          = "http://${Base}:${P_FFMPEG}"
    audio_extraction         = "http://${Base}:${P_AUDIO}"
    voice_activity_detection = "http://${Base}:${P_VAD}"
    dead_air_cut_planning    = "http://${Base}:${P_CUT_PLAN}"
    audio_enhancement        = "http://${Base}:${P_AUDIO_ENHANCE}"
    transcription            = "http://${Base}:${P_TRANSCRIPTION}"
}
$env:ORCHESTRATOR_SERVICE_ENDPOINTS = $endpoints | ConvertTo-Json -Compress

# ---------------------------------------------------------------------------
# Per-step HTTP timeouts
# ---------------------------------------------------------------------------
if (-not $env:ORCHESTRATOR_STEP_TIMEOUTS_JSON) {
    $timeouts = [ordered]@{
        audio_enhancement        = 600
        voice_activity_detection = 600
        transcription            = 1800
        body_detection           = 900
        proxy_frame_sampling     = 600
        ffmpeg_renderer          = 1800
    }
    $env:ORCHESTRATOR_STEP_TIMEOUTS_JSON = $timeouts | ConvertTo-Json -Compress
}

# ---------------------------------------------------------------------------
# Optional: prefetch transcription model
# ---------------------------------------------------------------------------
if ($PrefetchTranscriptionModel) {
    $prefetchModel   = if ($env:TRANSCRIPTION_WARMUP_MODEL)        { $env:TRANSCRIPTION_WARMUP_MODEL }        else { 'small' }
    $prefetchCompute = if ($env:TRANSCRIPTION_WARMUP_COMPUTE_TYPE) { $env:TRANSCRIPTION_WARMUP_COMPUTE_TYPE } else { 'int8' }
    Write-Host "Prefetching faster-whisper model before startup: model=$prefetchModel compute_type=$prefetchCompute"

    $prefetchScript = @"
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
    $prefetchScript | & "$RepoRoot\.venv\Scripts\python.exe" -
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# ---------------------------------------------------------------------------
# PID tracking
# ---------------------------------------------------------------------------
$PidsFile = "$RunDir\local_stack.pids"
Remove-Item $PidsFile -ErrorAction SilentlyContinue

$ServiceProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function Start-Uvicorn {
    param(
        [string]$Name,
        [string]$Port,
        [string]$Factory
    )
    $logOut = "$RunDir\logs\$Name.log"
    $logErr = "$RunDir\logs\$Name.err.log"
    $proc = Start-Process -FilePath $Uvicorn `
        -ArgumentList @($Factory, '--factory', '--host', $Base, '--port', $Port) `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError  $logErr `
        -PassThru -NoNewWindow
    $proc.Id | Add-Content $PidsFile
    $ServiceProcesses.Add($proc)
    Write-Host "Started $Name pid=$($proc.Id) port=$Port log=$logOut"
}

function Stop-AllServices {
    if (Test-Path $PidsFile) {
        Get-Content $PidsFile | ForEach-Object {
            $procId = [int]$_.Trim()
            if ($procId) {
                try {
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                } catch {}
            }
        }
        Remove-Item $PidsFile -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# Launch services
# ---------------------------------------------------------------------------
Write-Host "SMART_CUT_OBJECT_STORE_ROOT=$env:SMART_CUT_OBJECT_STORE_ROOT"
Write-Host "Orchestrator will call services on $Base ports $P_VALIDATION-$P_FFMPEG (vision/reframe), $P_AUDIO-$P_CUT_PLAN (dead-air), $P_AUDIO_ENHANCE-$P_TRANSCRIPTION (audio-quality)"

Start-Uvicorn 'validation'               $P_VALIDATION    'services.validation.api:create_app'
Start-Uvicorn 'media_metadata'           $P_META          'services.media_metadata.api:create_app'
Start-Uvicorn 'proxy_frame_sampling'     $P_PROXY         'services.proxy_frame_sampling.api:create_app'
Start-Uvicorn 'body_detection'           $P_BODY          'services.body_detection.api:create_app'
Start-Uvicorn 'track_interpolation'      $P_TRACK         'services.track_interpolation.api:create_app'
Start-Uvicorn 'reframe_planning'         $P_REFRAME       'services.reframe_planning.api:create_app'
Start-Uvicorn 'easing_smoothing'         $P_EASING        'services.easing_smoothing.api:create_app'
Start-Uvicorn 'render_plan_compiler'     $P_COMPILER      'services.render_plan_compiler.api:create_app'
Start-Uvicorn 'ffmpeg_renderer'          $P_FFMPEG        'services.ffmpeg_renderer.api:create_app'
Start-Uvicorn 'audio_extraction'         $P_AUDIO         'services.audio_extraction.api:create_app'
Start-Uvicorn 'voice_activity_detection' $P_VAD           'services.voice_activity_detection.api:create_app'
Start-Uvicorn 'dead_air_cut_planning'    $P_CUT_PLAN      'services.dead_air_cut_planning.api:create_app'
Start-Uvicorn 'audio_enhancement'        $P_AUDIO_ENHANCE 'services.audio_enhancement.api:create_app'
Start-Uvicorn 'transcription'            $P_TRANSCRIPTION 'services.transcription.api:create_app'

Start-Sleep -Seconds 2

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
if ($Detach) {
    $orchLogOut = "$RunDir\logs\orchestrator.log"
    $orchLogErr = "$RunDir\logs\orchestrator.err.log"
    $orchProc = Start-Process -FilePath $Uvicorn `
        -ArgumentList @('orchestrator.api:create_app', '--factory', '--host', $Base, '--port', $P_ORCH) `
        -RedirectStandardOutput $orchLogOut `
        -RedirectStandardError  $orchLogErr `
        -PassThru -NoNewWindow
    $orchProc.Id | Add-Content $PidsFile
    Write-Host "Started orchestrator pid=$($orchProc.Id) port=$P_ORCH log=$orchLogOut"
    Write-Host ""
    $frontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { '3000' }
    Write-Host "Detach mode: stop with  .\scripts\stop_local_stack.ps1"
    Write-Host "Frontend:    cd frontend ; npm run dev   -> http://localhost:$frontendPort"
    exit 0
}

# Foreground mode: orchestrator output shown in console, Ctrl+C cleans up everything
$orchProc = Start-Process -FilePath $Uvicorn `
    -ArgumentList @('orchestrator.api:create_app', '--factory', '--host', $Base, '--port', $P_ORCH) `
    -PassThru -NoNewWindow
$orchProc.Id | Add-Content $PidsFile
Write-Host "Orchestrator http://${Base}:${P_ORCH}  pid=$($orchProc.Id)  (Ctrl+C stops all services)"

try {
    $orchProc.WaitForExit()
} finally {
    Stop-AllServices
}
