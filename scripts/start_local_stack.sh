#!/usr/bin/env bash
# Start all Phase 1 microservices + Orchestrator on localhost so the HTTP pipeline
# produces a real final_9x16.mp4 under SMART_CUT_OBJECT_STORE_ROOT (default: repo/.orchestrator-data).
#
# Prerequisites: Python venv with requirements.txt, ffmpeg + ffprobe on PATH, Node (for frontend).
#
# Usage:
#   ./scripts/start_local_stack.sh              # foreground orchestrator (Ctrl+C stops everything)
#   ./scripts/start_local_stack.sh --detach     # background everything; logs under .run/logs/
#
# Then in another terminal:
#   cd frontend && npm run dev
# Open http://localhost:3000 — upload 16:9 video, Run pipeline, preview/download when done.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DETACH=false
if [[ "${1:-}" == "--detach" ]]; then
  DETACH=true
fi

UVICORN="${REPO_ROOT}/.venv/bin/uvicorn"
if [[ ! -x "$UVICORN" ]]; then
  echo "Missing ${UVICORN}. Run:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

for cmd in ffmpeg ffprobe; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing '$cmd' on PATH (required for media_metadata / proxy / renderer)."
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
P_VALIDATION=8010
P_META=8011
P_PROXY=8012
P_BODY=8013
P_TRACK=8014
P_REFRAME=8015
P_EASING=8016
P_COMPILER=8017
P_FFMPEG=8018
P_ORCH=8000

export ORCHESTRATOR_SERVICE_ENDPOINTS="$(printf '%s' "{
  \"validation\": \"http://${BASE}:${P_VALIDATION}\",
  \"media_metadata\": \"http://${BASE}:${P_META}\",
  \"proxy_frame_sampling\": \"http://${BASE}:${P_PROXY}\",
  \"body_detection\": \"http://${BASE}:${P_BODY}\",
  \"track_interpolation\": \"http://${BASE}:${P_TRACK}\",
  \"reframe_planning\": \"http://${BASE}:${P_REFRAME}\",
  \"easing_smoothing\": \"http://${BASE}:${P_EASING}\",
  \"render_plan_compiler\": \"http://${BASE}:${P_COMPILER}\",
  \"ffmpeg_renderer\": \"http://${BASE}:${P_FFMPEG}\"
}")"

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
echo "Orchestrator will call services on ${BASE} ports ${P_VALIDATION}-${P_FFMPEG}"

start_uvicorn "validation" "${P_VALIDATION}" "services.validation.api:create_app"
start_uvicorn "media_metadata" "${P_META}" "services.media_metadata.api:create_app"
start_uvicorn "proxy_frame_sampling" "${P_PROXY}" "services.proxy_frame_sampling.api:create_app"
start_uvicorn "body_detection" "${P_BODY}" "services.body_detection.api:create_app"
start_uvicorn "track_interpolation" "${P_TRACK}" "services.track_interpolation.api:create_app"
start_uvicorn "reframe_planning" "${P_REFRAME}" "services.reframe_planning.api:create_app"
start_uvicorn "easing_smoothing" "${P_EASING}" "services.easing_smoothing.api:create_app"
start_uvicorn "render_plan_compiler" "${P_COMPILER}" "services.render_plan_compiler.api:create_app"
start_uvicorn "ffmpeg_renderer" "${P_FFMPEG}" "services.ffmpeg_renderer.api:create_app"

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
