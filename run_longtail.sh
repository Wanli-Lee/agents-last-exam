#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/home/wanli/.venvs/agent_hle_ale}"
export UV_LINK_MODE="${UV_LINK_MODE:-hardlink}"
NODE_BIN_DIR="$(dirname "$(command -v node 2>/dev/null || echo /home/wanli/.nvm/versions/node/v22.21.0/bin/node)")"
export PATH="${NODE_BIN_DIR}:${PATH}"
PORT="${LITELLM_PORT:-4200}"
PID="$(ss -tlnp 2>/dev/null | awk -v p=":${PORT}" '$0 ~ p {print $0}' | grep -oP 'pid=\K[0-9]+' | head -1)"
[ -z "${PID:-}" ] && { echo "LiteLLM not on :${PORT}"; exit 2; }
OPENAI_API_KEY="$(python3 - "$PID" <<'PY'
import sys
for item in open(f"/proc/{sys.argv[1]}/environ","rb").read().split(b"\0"):
    if item.startswith(b"LITELLM_MASTER_KEY="): print(item.split(b"=",1)[1].decode()); break
PY
)"
export OPENAI_API_KEY OPENAI_API_BASE="http://127.0.0.1:${PORT}/v1" OPENAI_BASE_URL="http://127.0.0.1:${PORT}/v1" LLM_JUDGE_MODEL="gpt-5.5"
unset all_proxy ALL_PROXY SOCKS_PROXY socks_proxy http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
export NO_PROXY="127.0.0.1,localhost,0.0.0.0,::1" no_proxy="127.0.0.1,localhost,0.0.0.0,::1"
exec env -u all_proxy -u ALL_PROXY -u SOCKS_PROXY -u socks_proxy -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  /home/wanli/.local/bin/uv run python -m ale_run run ale_claw_gpt55_longtail.yaml --resume "$@"
