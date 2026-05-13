param(
    [switch]$Detach,
    [switch]$PrefetchTranscriptionModel
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-EnvOrDefault {
    param(
        [string]$Name,
        [string]$DefaultValue
    )

    $currentValue = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($currentValue)) {
        return $DefaultValue
    }

    return $currentValue
}

function Import-EnvFile {
    param([string]$Path)

    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
            continue
        }

        $separatorIndex = $line.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $name = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()

        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Add-Pid {
    param([int]$Id)

    Add-Content -Path $script:PidsFile -Value $Id
}

function Stop-StartedProcesses {
    if (-not (Test-Path -Path $script:PidsFile)) {
        return
    }

    foreach ($pidLine in Get-Content -Path $script:PidsFile) {
        if ([string]::IsNullOrWhiteSpace($pidLine)) {
            continue
        }

        try {
            Stop-Process -Id ([int]$pidLine) -ErrorAction Stop
        }
        catch {
        }
    }

    Remove-Item -Path $script:PidsFile -Force -ErrorAction SilentlyContinue
}

function Start-UvicornService {
    param(
        [string]$Name,
        [string]$Port,
        [string]$Factory
    )

    $stdoutLog = Join-Path $script:LogsDir ("{0}.stdout.log" -f $Name)
    $stderrLog = Join-Path $script:LogsDir ("{0}.stderr.log" -f $Name)
    $process = Start-Process -FilePath $script:Uvicorn -ArgumentList @(
        $Factory,
        "--factory",
        "--host",
        $script:Base,
        "--port",
        $Port
    ) -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru

    Add-Pid -Id $process.Id
    Write-Host ("Started {0} pid={1} port={2} logs={3}, {4}" -f $Name, $process.Id, $Port, $stdoutLog, $stderrLog)
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -Path $RepoRoot

$envFile = Join-Path $RepoRoot ".env.local"
if (Test-Path -Path $envFile) {
    Import-EnvFile -Path $envFile
}

$script:Uvicorn = Join-Path $RepoRoot ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path -Path $script:Uvicorn)) {
    throw "Missing $script:Uvicorn. Run: py -3 -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
}

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -Path $pythonExe)) {
    throw "Missing $pythonExe. Run: py -3 -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
}

foreach ($commandName in @("ffmpeg", "ffprobe")) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Missing '$commandName' on PATH (required for media services)."
    }
}

if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $RepoRoot
}
else {
    $env:PYTHONPATH = "$RepoRoot;$($env:PYTHONPATH)"
}

$env:SMART_CUT_OBJECT_STORE_ROOT = Get-EnvOrDefault -Name "SMART_CUT_OBJECT_STORE_ROOT" -DefaultValue (Join-Path $RepoRoot ".orchestrator-data")
New-Item -ItemType Directory -Path $env:SMART_CUT_OBJECT_STORE_ROOT -Force | Out-Null

$runDir = Join-Path $RepoRoot ".run"
$script:LogsDir = Join-Path $runDir "logs"
New-Item -ItemType Directory -Path $script:LogsDir -Force | Out-Null

$env:ORCHESTRATOR_MINIO_BUCKET = Get-EnvOrDefault -Name "ORCHESTRATOR_MINIO_BUCKET" -DefaultValue "smart-cut"

$script:Base = Get-EnvOrDefault -Name "LOCAL_STACK_HOST" -DefaultValue "127.0.0.1"

$P_VALIDATION = Get-EnvOrDefault -Name "VALIDATION_PORT" -DefaultValue "8010"
$P_META = Get-EnvOrDefault -Name "MEDIA_METADATA_PORT" -DefaultValue "8011"
$P_PROXY = Get-EnvOrDefault -Name "PROXY_FRAME_SAMPLING_PORT" -DefaultValue "8012"
$P_BODY = Get-EnvOrDefault -Name "BODY_DETECTION_PORT" -DefaultValue "8013"
$P_TRACK = Get-EnvOrDefault -Name "TRACK_INTERPOLATION_PORT" -DefaultValue "8014"
$P_REFRAME = Get-EnvOrDefault -Name "REFRAME_PLANNING_PORT" -DefaultValue "8015"
$P_EASING = Get-EnvOrDefault -Name "EASING_SMOOTHING_PORT" -DefaultValue "8016"
$P_COMPILER = Get-EnvOrDefault -Name "RENDER_PLAN_COMPILER_PORT" -DefaultValue "8017"
$P_FFMPEG = Get-EnvOrDefault -Name "FFMPEG_RENDERER_PORT" -DefaultValue "8018"

$P_AUDIO = Get-EnvOrDefault -Name "AUDIO_EXTRACTION_PORT" -DefaultValue "8019"
$P_VAD = Get-EnvOrDefault -Name "VOICE_ACTIVITY_DETECTION_PORT" -DefaultValue "8020"
$P_CUT_PLAN = Get-EnvOrDefault -Name "DEAD_AIR_CUT_PLANNING_PORT" -DefaultValue "8021"

$P_AUDIO_ENHANCE = Get-EnvOrDefault -Name "AUDIO_ENHANCEMENT_PORT" -DefaultValue "8022"
$P_TRANSCRIPTION = Get-EnvOrDefault -Name "TRANSCRIPTION_PORT" -DefaultValue "8023"

$P_ORCH = Get-EnvOrDefault -Name "ORCHESTRATOR_PORT" -DefaultValue "8000"

$serviceEndpoints = [ordered]@{
    validation = "http://$($script:Base):$P_VALIDATION"
    media_metadata = "http://$($script:Base):$P_META"
    proxy_frame_sampling = "http://$($script:Base):$P_PROXY"
    body_detection = "http://$($script:Base):$P_BODY"
    track_interpolation = "http://$($script:Base):$P_TRACK"
    reframe_planning = "http://$($script:Base):$P_REFRAME"
    easing_smoothing = "http://$($script:Base):$P_EASING"
    render_plan_compiler = "http://$($script:Base):$P_COMPILER"
    ffmpeg_renderer = "http://$($script:Base):$P_FFMPEG"
    audio_extraction = "http://$($script:Base):$P_AUDIO"
    voice_activity_detection = "http://$($script:Base):$P_VAD"
    dead_air_cut_planning = "http://$($script:Base):$P_CUT_PLAN"
    audio_enhancement = "http://$($script:Base):$P_AUDIO_ENHANCE"
    transcription = "http://$($script:Base):$P_TRANSCRIPTION"
}
$env:ORCHESTRATOR_SERVICE_ENDPOINTS = $serviceEndpoints | ConvertTo-Json -Compress

$defaultTimeouts = [ordered]@{
    audio_enhancement = 600
    voice_activity_detection = 600
    transcription = 1800
    body_detection = 900
    proxy_frame_sampling = 600
    ffmpeg_renderer = 1800
}
if ([string]::IsNullOrWhiteSpace($env:ORCHESTRATOR_STEP_TIMEOUTS_JSON)) {
    $env:ORCHESTRATOR_STEP_TIMEOUTS_JSON = $defaultTimeouts | ConvertTo-Json -Compress
}

if ($PrefetchTranscriptionModel) {
    $prefetchModel = Get-EnvOrDefault -Name "TRANSCRIPTION_WARMUP_MODEL" -DefaultValue "small"
    $prefetchComputeType = Get-EnvOrDefault -Name "TRANSCRIPTION_WARMUP_COMPUTE_TYPE" -DefaultValue "int8"
    Write-Host ("Prefetching faster-whisper model before startup: model={0} compute_type={1}" -f $prefetchModel, $prefetchComputeType)
    $prefetchCode = @'
import os
import sys

from services.transcription.service import warmup_model

model_name = os.getenv("TRANSCRIPTION_WARMUP_MODEL", "small")
compute_type = os.getenv("TRANSCRIPTION_WARMUP_COMPUTE_TYPE", "int8")
ok, error = warmup_model(model_name=model_name, compute_type=compute_type)
if not ok:
    print(f"Prefetch failed for model={model_name} compute_type={compute_type}: {error}")
    sys.exit(1)
print(f"Prefetch complete for model={model_name} compute_type={compute_type}")
'@
    & $pythonExe -c $prefetchCode
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$script:PidsFile = Join-Path $runDir "local_stack.pids"
if (Test-Path -Path $script:PidsFile) {
    Remove-Item -Path $script:PidsFile -Force
}

Write-Host "SMART_CUT_OBJECT_STORE_ROOT=$($env:SMART_CUT_OBJECT_STORE_ROOT)"
Write-Host ("Orchestrator will call services on {0} ports {1}-{2} (vision/reframe), {3}-{4} (dead-air), {5}-{6} (audio-quality)" -f $script:Base, $P_VALIDATION, $P_FFMPEG, $P_AUDIO, $P_CUT_PLAN, $P_AUDIO_ENHANCE, $P_TRANSCRIPTION)

Start-UvicornService -Name "validation" -Port $P_VALIDATION -Factory "services.validation.api:create_app"
Start-UvicornService -Name "media_metadata" -Port $P_META -Factory "services.media_metadata.api:create_app"
Start-UvicornService -Name "proxy_frame_sampling" -Port $P_PROXY -Factory "services.proxy_frame_sampling.api:create_app"
Start-UvicornService -Name "body_detection" -Port $P_BODY -Factory "services.body_detection.api:create_app"
Start-UvicornService -Name "track_interpolation" -Port $P_TRACK -Factory "services.track_interpolation.api:create_app"
Start-UvicornService -Name "reframe_planning" -Port $P_REFRAME -Factory "services.reframe_planning.api:create_app"
Start-UvicornService -Name "easing_smoothing" -Port $P_EASING -Factory "services.easing_smoothing.api:create_app"
Start-UvicornService -Name "render_plan_compiler" -Port $P_COMPILER -Factory "services.render_plan_compiler.api:create_app"
Start-UvicornService -Name "ffmpeg_renderer" -Port $P_FFMPEG -Factory "services.ffmpeg_renderer.api:create_app"
Start-UvicornService -Name "audio_extraction" -Port $P_AUDIO -Factory "services.audio_extraction.api:create_app"
Start-UvicornService -Name "voice_activity_detection" -Port $P_VAD -Factory "services.voice_activity_detection.api:create_app"
Start-UvicornService -Name "dead_air_cut_planning" -Port $P_CUT_PLAN -Factory "services.dead_air_cut_planning.api:create_app"
Start-UvicornService -Name "audio_enhancement" -Port $P_AUDIO_ENHANCE -Factory "services.audio_enhancement.api:create_app"
Start-UvicornService -Name "transcription" -Port $P_TRANSCRIPTION -Factory "services.transcription.api:create_app"

Start-Sleep -Seconds 2

if ($Detach) {
    $orchStdout = Join-Path $script:LogsDir "orchestrator.stdout.log"
    $orchStderr = Join-Path $script:LogsDir "orchestrator.stderr.log"
    $orchestratorProcess = Start-Process -FilePath $script:Uvicorn -ArgumentList @(
        "orchestrator.api:create_app",
        "--factory",
        "--host",
        $script:Base,
        "--port",
        $P_ORCH
    ) -RedirectStandardOutput $orchStdout -RedirectStandardError $orchStderr -PassThru
    Add-Pid -Id $orchestratorProcess.Id
    Write-Host ("Started orchestrator pid={0} port={1} logs={2}, {3}" -f $orchestratorProcess.Id, $P_ORCH, $orchStdout, $orchStderr)
    Write-Host ""
    Write-Host "Detach mode: stop with .\scripts\stop_local_stack.ps1"
    Write-Host ("Frontend:     cd frontend; npm run dev   -> http://localhost:{0}" -f (Get-EnvOrDefault -Name "FRONTEND_PORT" -DefaultValue "3000"))
    exit 0
}

Write-Host ("Orchestrator http://{0}:{1} (Ctrl+C stops all services)" -f $script:Base, $P_ORCH)
try {
    & $script:Uvicorn "orchestrator.api:create_app" --factory --host $script:Base --port $P_ORCH
    exit $LASTEXITCODE
}
finally {
    Stop-StartedProcesses
}