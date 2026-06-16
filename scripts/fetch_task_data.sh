#!/usr/bin/env bash
# Fetch the ALE task data for the local Docker provider.
#
# The task data (input + software + reference for the Linux subset) is published
# as a single GATED archive on Hugging Face. This script downloads and extracts
# it into the directory the docker.yaml `local:` task-data source reads from.
#
# Prerequisites (one-time):
#   1. Request access:  https://huggingface.co/datasets/agents-last-exam/agents-last-exam-data-archive
#   2. Log in:          huggingface-cli login        (pip install huggingface_hub)
#
# Usage:
#   scripts/fetch_task_data.sh [DEST]
#     DEST  target dir (default: task-data, matching `task_data_source: local:task-data`)
#
# The published image (agentslastexam/ale-ubuntu22-docker:latest) is data-less,
# so this is the only data you need to run the docker provider locally.
set -euo pipefail

REPO="agents-last-exam/agents-last-exam-data-archive"
FILE="ale-tasks-data.tar.gz"
DEST="${1:-task-data}"

command -v huggingface-cli >/dev/null 2>&1 \
  || { echo "ERROR: huggingface-cli not found — run: pip install huggingface_hub" >&2; exit 1; }

mkdir -p "$DEST"
echo ">> Downloading $FILE from $REPO (gated: needs approved access + huggingface-cli login) ..."
tarball="$(huggingface-cli download "$REPO" "$FILE" --repo-type dataset --local-dir "$DEST")"

echo ">> Extracting into $DEST/ ..."
tar xzf "$tarball" -C "$DEST"
rm -f "$tarball"

echo ">> Done. Layout: $DEST/<domain>/<task>/<variant>/{input,software,reference}"
echo ">> docker.yaml already points at it via:  task_data_source: local:$DEST"
