#!/usr/bin/env bash
# Stop processes started by scripts/start_local_stack.sh (--detach or leftover PIDs).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS_FILE="${REPO_ROOT}/.run/local_stack.pids"

if [[ ! -f "${PIDS_FILE}" ]]; then
  echo "No ${PIDS_FILE} — nothing to stop (or stack was not started via start_local_stack.sh)."
  exit 0
fi

while read -r pid; do
  [[ -n "${pid}" ]] || continue
  if kill "${pid}" 2>/dev/null; then
    echo "Stopped pid ${pid}"
  fi
done <"${PIDS_FILE}"

rm -f "${PIDS_FILE}"
echo "Done."
