#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing ${PYTHON_BIN}. Run:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
MODEL_NAME="${TRANSCRIPTION_WARMUP_MODEL:-small}"
COMPUTE_TYPE="${TRANSCRIPTION_WARMUP_COMPUTE_TYPE:-int8}"

echo "Prefetching faster-whisper model=${MODEL_NAME} compute_type=${COMPUTE_TYPE}"
"${PYTHON_BIN}" - <<'PY'
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
