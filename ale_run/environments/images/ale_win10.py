"""``ale-win10`` — Windows 10 baked image with node + cua-mcp-server.

Counterpart to :mod:`.ale_ubuntu22`. Same field set; absolute paths as
seen on this image. ``task_data_root`` sits on the boot disk (E: drive)
which is baked into the image."""
from __future__ import annotations

from . import Image


IMAGE = Image(
    name="ale-win10",
    os="windows",

    # sandbox-side paths
    work_dir_base=r"C:\Users\User\.ale",
    task_data_root=r"E:\ale-data",
    node=r"C:\Users\User\node-v24.12.0-win-x64\node.exe",
    python=r"C:\Python313\python.exe",
    mcp_server_dir=r"C:\Users\User\cua_mcp_server",

    # provisioning defaults
    default_machine_type="n2-standard-4",
)
