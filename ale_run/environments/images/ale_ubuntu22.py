"""``ale-ubuntu22`` — Ubuntu 22.04 baked image with node + cua-mcp-server.

VM-side absolute paths the deployer can rely on without discovery.
Agent-specific binaries (``claude``, ``codex``, ...) are NOT in here —
each deployer discovers its own binary at install time so a new image
family doesn't force a framework-level change.
"""
from __future__ import annotations

from . import Image


IMAGE = Image(
    name="ale-ubuntu22",
    os="linux",

    # sandbox-side paths
    work_dir_base="/home/user/.ale",
    task_data_root="/media/user/data/ale-data",
    node="/usr/local/bin/node",
    python="/usr/bin/python3",
    mcp_server_dir="/home/user/cua_mcp_server",

    # provisioning defaults
    default_machine_type="e2-standard-4",
)
