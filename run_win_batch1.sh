#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
export UV_PROJECT_ENVIRONMENT="/home/wanli/.venvs/agent_hle_ale"
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
set -a; source secret/.env; set +a
PORT=4200
PID="$(ss -tlnp 2>/dev/null | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | head -1)"
[ -z "${PID:-}" ] && { echo "LiteLLM proxy not on :${PORT}"; exit 2; }
export OPENAI_API_KEY="$(python3 -c "
for it in open('/proc/$PID/environ','rb').read().split(b'\0'):
    if it.startswith(b'LITELLM_MASTER_KEY='): print(it.split(b'=',1)[1].decode()); break
")"
export OPENAI_API_BASE="http://127.0.0.1:${PORT}/v1"
export OPENAI_BASE_URL="$OPENAI_API_BASE"
export LLM_JUDGE_MODEL="${LLM_JUDGE_MODEL:-gpt-5.5}"
# web_search (serper) + web_fetch run host-side via aiohttp trust_env=True, so
# they honor HTTPS_PROXY for out-of-GFW sites. NO_PROXY keeps the localhost
# LiteLLM proxy (:4200) and gcloud-internal traffic on a direct connection.
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7897}"
export NO_PROXY="127.0.0.1,localhost,0.0.0.0,::1"
export no_proxy="$NO_PROXY"
exec /home/wanli/.local/bin/uv run --no-sync python -m ale_run run win_batch1.yaml "$@"
