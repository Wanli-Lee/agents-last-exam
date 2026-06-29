"""``ale-cua-local`` — locally-built amd64 Ubuntu sandbox for ALE.

NON-PAPER local alternative for amd64 hosts. The published ``ale-kasm`` image
is arm64-only, so on an amd64 host we build our own sandbox from
``wildclawbench-ubuntu`` + ``cua-computer-server`` (pip) + Xvfb. The cua-server
runs on port 8000 via ``/usr/local/bin/ale-cua-start.sh`` (boots Xvfb :99 then
``python3 -m computer_server``). Task data is staged from the host with the
``local://`` backend (docker cp), so this image bakes no task data.

Container user is root; system Python 3.10 at /usr/bin/python3, node at
/usr/bin/node.
"""
from __future__ import annotations

from . import Image


IMAGE = Image(
    name="ale-cua-local",
    os="linux",

    # sandbox-side paths
    work_dir_base="/root/.ale",
    task_data_root="/media/user/data/agenthle",
    node="/usr/bin/node",
    python="/usr/bin/python3",
    mcp_server_dir="/root/cua_mcp_server",

    # docker containers sized by host
    default_machine_type="",

    # locally-built/committed image tag
    docker_image="ale-cua-local:amd64",

    # cua-computer-server default port
    cua_server_port=8000,
)
