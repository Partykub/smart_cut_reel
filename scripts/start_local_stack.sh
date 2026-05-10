#!/usr/bin/env bash
# Start all microservices + Orchestrator on localhost so the HTTP pipeline
# produces a real final_9x16.mp4 under SMART_CUT_OBJECT_STORE_ROOT (default: repo/.orchestrator-data).
#
# Vision/reframe stack (8010–8018): validation, media_metadata, proxy_frame_sampling,
#   body_detection, track_interpolation, reframe_planning, easing_smoothing,
#   render_plan_compiler, ffmpeg_renderer.
# Dead-air chain (8019–8021): audio_extraction, voice_activity_detection, dead_air_cut_planning.
# Audio-quality chain (8022–8023): audio_enhancement, transcription.
#
# Prerequisites: Python venv with requirements.txt, ffmpeg + ffprobe on PATH, Node (for frontend).
#
# Usage:
#   ./scripts/start_local_stack.sh                           # foreground orchestrator (Ctrl+C stops everything)
#   ./scripts/start_local_stack.sh --detach                  # background everything; logs under .run/logs/
#   ./scripts/start_local_stack.sh --prefetch-transcription-model
#       # pre-download/load faster-whisper model before services boot
#
# Then in another terminal:
#   cd frontend && npm run dev
# Open http://localhost:3000 — upload 16:9 video, choose pipeline, Run, preview/download when done.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DETACH=false
PREFETCH_TRANSCRIPTION_MODEL=false
for arg in "$@"; do
  case "$arg" in
    --detach)
      DETACH=true
      ;;
    --prefetch-transcription-model)
      PREFETCH_TRANSCRIPTION_MODEL=true
      ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: ./scripts/start_local_stack.sh [--detach] [--prefetch-transcription-model]"
      exit 1
      ;;
  esac
done

UVICORN="${REPO_ROOT}/.venv/bin/uvicorn"
if [[ ! -x "$UVICORN" ]]; then
  echo "Missing ${UVICORN}. Run:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

for cmd in ffmpeg ffprobe; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing '$cmd' on PATH (required for media_metadata / proxy / renderer / audio_extraction)."
    exit 1
  fi
done

export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export SMART_CUT_OBJECT_STORE_ROOT="${SMART_CUT_OBJECT_STORE_ROOT:-${REPO_ROOT}/.orchestrator-data}"
mkdir -p "${SMART_CUT_OBJECT_STORE_ROOT}"

RUN_DIR="${REPO_ROOT}/.run"
mkdir -p "${RUN_DIR}/logs"

export ORCHESTRATOR_MINIO_BUCKET="${ORCHESTRATOR_MINIO_BUCKET:-smart-cut}"

BASE="${LOCAL_STACK_HOST:-127.0.0.1}"

# Phase 1 vision pipeline
P_VALIDATION=8010
P_META=8011
P_PROXY=8012
P_BODY=8013
P_TRACK=8014
P_REFRAME=8015
P_EASING=8016
P_COMPILER=8017
P_FFMPEG=8018

# Phase 2 audio pipeline
P_AUDIO=8019
P_VAD=8020
P_CUT_PLAN=8021

# Phase 3 audio quality chain
P_AUDIO_ENHANCE=8022
P_TRANSCRIPTION=8023

P_ORCH=8000

ORCHESTRATOR_SERVICE_ENDPOINTS_JSON='{'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"validation":"http://'"${BASE}:${P_VALIDATION}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"media_metadata":"http://'"${BASE}:${P_META}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"proxy_frame_sampling":"http://'"${BASE}:${P_PROXY}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"body_detection":"http://'"${BASE}:${P_BODY}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"track_interpolation":"http://'"${BASE}:${P_TRACK}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"reframe_planning":"http://'"${BASE}:${P_REFRAME}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"easing_smoothing":"http://'"${BASE}:${P_EASING}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"render_plan_compiler":"http://'"${BASE}:${P_COMPILER}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"ffmpeg_renderer":"http://'"${BASE}:${P_FFMPEG}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"audio_extraction":"http://'"${BASE}:${P_AUDIO}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"voice_activity_detection":"http://'"${BASE}:${P_VAD}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"dead_air_cut_planning":"http://'"${BASE}:${P_CUT_PLAN}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"audio_enhancement":"http://'"${BASE}:${P_AUDIO_ENHANCE}"'",'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='"transcription":"http://'"${BASE}:${P_TRANSCRIPTION}"'"'
ORCHESTRATOR_SERVICE_ENDPOINTS_JSON+='}'
export ORCHESTRATOR_SERVICE_ENDPOINTS="${ORCHESTRATOR_SERVICE_ENDPOINTS_JSON}"

# Per-step HTTP timeouts (seconds). Heavy AI / ffmpeg steps need more than
# the 600s default, especially the very first transcription /run on a fresh
# install where faster-whisper has to download the model weights.
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT='{'
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT+='"audio_enhancement":600,'
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT+='"voice_activity_detection":600,'
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT+='"transcription":1800,'
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT+='"body_detection":900,'
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT+='"proxy_frame_sampling":600,'
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT+='"ffmpeg_renderer":1800'
ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT+='}'
export ORCHESTRATOR_STEP_TIMEOUTS_JSON="${ORCHESTRATOR_STEP_TIMEOUTS_JSON:-${ORCHESTRATOR_STEP_TIMEOUTS_JSON_DEFAULT}}"

if [[ "${PREFETCH_TRANSCRIPTION_MODEL}" == true ]]; then
  PREFETCH_MODEL="${TRANSCRIPTION_WARMUP_MODEL:-small}"
  PREFETCH_COMPUTE_TYPE="${TRANSCRIPTION_WARMUP_COMPUTE_TYPE:-int8}"
  echo "Prefetching faster-whisper model before startup: model=${PREFETCH_MODEL} compute_type=${PREFETCH_COMPUTE_TYPE}"
  "${REPO_ROOT}/.venv/bin/python" - <<'PY'
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
PY
fi

PIDS_FILE="${RUN_DIR}/local_stack.pids"
rm -f "${PIDS_FILE}"

start_uvicorn() {
  local name="$1"
  local port="$2"
  local factory="$3"
  local log="${RUN_DIR}/logs/${name}.log"
  if [[ "$DETACH" == true ]]; then
    nohup "${UVICORN}" "${factory}" --factory --host "${BASE}" --port "${port}" \
      >>"${log}" 2>&1 &
    echo $! >>"${PIDS_FILE}"
    echo "Started ${name} pid=$! port=${port} log=${log}"
  else
    "${UVICORN}" "${factory}" --factory --host "${BASE}" --port "${port}" \
      >>"${log}" 2>&1 &
    echo $! >>"${PIDS_FILE}"
    echo "Started ${name} pid=$! port=${port} log=${log}"
  fi
}

cleanup() {
  if [[ -f "${PIDS_FILE}" ]]; then
    while read -r pid; do
      [[ -n "${pid}" ]] || continue
      kill "${pid}" 2>/dev/null || true
    done <"${PIDS_FILE}"
    rm -f "${PIDS_FILE}"
  fi
}

if [[ "$DETACH" == false ]]; then
  trap cleanup EXIT INT TERM
fi

echo "SMART_CUT_OBJECT_STORE_ROOT=${SMART_CUT_OBJECT_STORE_ROOT}"
echo "Orchestrator will call services on ${BASE} ports ${P_VALIDATION}-${P_FFMPEG} (vision/reframe), ${P_AUDIO}-${P_CUT_PLAN} (dead-air), ${P_AUDIO_ENHANCE}-${P_TRANSCRIPTION} (audio-quality)"

start_uvicorn "validation" "${P_VALIDATION}" "services.validation.api:create_app"
start_uvicorn "media_metadata" "${P_META}" "services.media_metadata.api:create_app"
start_uvicorn "proxy_frame_sampling" "${P_PROXY}" "services.proxy_frame_sampling.api:create_app"
start_uvicorn "body_detection" "${P_BODY}" "services.body_detection.api:create_app"
start_uvicorn "track_interpolation" "${P_TRACK}" "services.track_interpolation.api:create_app"
start_uvicorn "reframe_planning" "${P_REFRAME}" "services.reframe_planning.api:create_app"
start_uvicorn "easing_smoothing" "${P_EASING}" "services.easing_smoothing.api:create_app"
start_uvicorn "render_plan_compiler" "${P_COMPILER}" "services.render_plan_compiler.api:create_app"
start_uvicorn "ffmpeg_renderer" "${P_FFMPEG}" "services.ffmpeg_renderer.api:create_app"
start_uvicorn "audio_extraction" "${P_AUDIO}" "services.audio_extraction.api:create_app"
start_uvicorn "voice_activity_detection" "${P_VAD}" "services.voice_activity_detection.api:create_app"
start_uvicorn "dead_air_cut_planning" "${P_CUT_PLAN}" "services.dead_air_cut_planning.api:create_app"
start_uvicorn "audio_enhancement" "${P_AUDIO_ENHANCE}" "services.audio_enhancement.api:create_app"
start_uvicorn "transcription" "${P_TRANSCRIPTION}" "services.transcription.api:create_app"

sleep 2

if [[ "$DETACH" == true ]]; then
  nohup "${UVICORN}" orchestrator.api:create_app --factory --host "${BASE}" --port "${P_ORCH}" \
    >>"${RUN_DIR}/logs/orchestrator.log" 2>&1 &
  echo $! >>"${PIDS_FILE}"
  echo "Started orchestrator pid=$! port=${P_ORCH} log=${RUN_DIR}/logs/orchestrator.log"
  echo ""
  echo "Detach mode: stop with  ./scripts/stop_local_stack.sh"
  echo "Frontend:     cd frontend && npm run dev   → http://localhost:3000"
  exit 0
fi

echo "Orchestrator http://${BASE}:${P_ORCH} (logs below; Ctrl+C stops all services)"
"${UVICORN}" orchestrator.api:create_app --factory --host "${BASE}" --port "${P_ORCH}" &
ORCH_PID=$!
echo "${ORCH_PID}" >>"${PIDS_FILE}"
wait "${ORCH_PID}"
