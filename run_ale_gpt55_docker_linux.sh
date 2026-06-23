#!/usr/bin/env bash
# NON-PAPER local Docker run: ALE Linux subset (cpu-free-ubuntu) on ale-kasm,
# driven by GPT-5.5 via the local LiteLLM proxy on :4200. No GCP required.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/home/wanli/.venvs/agent_hle_ale}"
export UV_LINK_MODE="${UV_LINK_MODE:-hardlink}"

# Node (MCP bridge) runs on the host for the docker executor.
NODE_BIN_DIR="$(dirname "$(command -v node 2>/dev/null || echo /home/wanli/.nvm/versions/node/v22.21.0/bin/node)")"
export PATH="${NODE_BIN_DIR}:${PATH}"

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
  echo "LITELLM_MASTER_KEY not found in LiteLLM process environment" >&2
  exit 3
fi

export OPENAI_API_KEY
export OPENAI_API_BASE="http://127.0.0.1:${PORT}/v1"
export OPENAI_BASE_URL="$OPENAI_API_BASE"
export LLM_JUDGE_MODEL="${LLM_JUDGE_MODEL:-gpt-5.5}"

# Proxy hygiene: the cua SDK drives the in-container computer-server over
# WebSockets via localhost:<mapped-port>. The `websockets` lib honors
# `all_proxy`/`ALL_PROXY` (SOCKS), so any inherited proxy silently breaks the
# connection. Strip SOCKS/all_proxy entirely and force every local target to
# bypass HTTP proxies. The MCP bridge npm deps are already vendored, so no
# outbound proxy is needed for a run.
unset all_proxy ALL_PROXY SOCKS_PROXY socks_proxy
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
export NO_PROXY="127.0.0.1,localhost,0.0.0.0,::1"
export no_proxy="$NO_PROXY"

exec env -u all_proxy -u ALL_PROXY -u SOCKS_PROXY -u socks_proxy \
         -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  /home/wanli/.local/bin/uv run python -m ale_run run ale_claw_gpt55_docker_linux.yaml --resume "$@"
