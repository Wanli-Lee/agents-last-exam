#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/home/wanli/.venvs/agent_hle_ale}"
export UV_LINK_MODE="${UV_LINK_MODE:-hardlink}"

if [ -f secret/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source secret/.env
  set +a
fi

PORT="${LITELLM_PORT:-4200}"
PID="$(ss -tlnp 2>/dev/null | awk -v p=":${PORT}" '$0 ~ p {print $0}' | grep -oP 'pid=\K[0-9]+' | head -1)"
if [ -z "${PID:-}" ]; then
  echo "LiteLLM proxy is not listening on port ${PORT}" >&2
  exit 2
fi

OPENAI_API_KEY="$(
  python3 - "$PID" <<'PY'
import sys
pid = sys.argv[1]
for item in open(f"/proc/{pid}/environ", "rb").read().split(b"\0"):
    if item.startswith(b"LITELLM_MASTER_KEY="):
        print(item.split(b"=", 1)[1].decode())
        break
PY
)"
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "LITELLM_MASTER_KEY was not found in LiteLLM process environment" >&2
  exit 3
fi

export OPENAI_API_KEY
export OPENAI_API_BASE="http://127.0.0.1:${PORT}/v1"
export OPENAI_BASE_URL="$OPENAI_API_BASE"
export LLM_JUDGE_MODEL="${LLM_JUDGE_MODEL:-gpt-5.5}"
export NO_PROXY="127.0.0.1,localhost,0.0.0.0,::1,${NO_PROXY:-}"
export no_proxy="$NO_PROXY"

: "${GCP_PROJECT:?Set GCP_PROJECT in secret/.env or the shell before running}"
: "${GCP_SA_KEY:?Set GCP_SA_KEY in secret/.env or the shell before running}"

exec /home/wanli/.local/bin/uv run python -m ale_run run ale_claw_gpt55_4200_full.yaml --resume "$@"
