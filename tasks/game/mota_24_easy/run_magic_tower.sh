#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="${1:-tasks/game/mota_24_easy}"
MODEL="${2:-openai/computer-use-preview}"

if [[ -z "${CUA_ENV_API_URL:-}" ]]; then
  echo "CUA_ENV_API_URL must point to a Cua-compatible desktop endpoint." >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  PYTHON_RUNNER=(uv run python)
else
  PYTHON_RUNNER=("${PYTHON_BIN:-python3}")
fi

"${PYTHON_RUNNER[@]}" -m cua_bench.batch.solver "$TASK_DIR" \
  --eval \
  --agent "${ALE_AGENT_NAME:-computer-use-agent}" \
  --model "$MODEL" \
  --max-steps "${MAX_STEPS:-500}" \
  --output-dir "${EVALUATION_OUTPUT_DIR:-./trycua/cua-bench/mota_24_easy}"
