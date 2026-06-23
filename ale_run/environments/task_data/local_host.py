"""``task_data_source: local://<host_root>`` — stage task data from a host dir.

Non-paper local alternative for the docker provider. ``<host_root>`` is a
host-side directory that mirrors the published ALE data layout::

    <host_root>/data/tasks/<domain>/<task>/<variant>/input/      (and software/)
    <host_root>/reference/tasks/<domain>/<task>/<variant>/reference/

Files are pushed into the running container with ``docker cp`` (fast, no cua
HTTP round-trips), then chowned to the container user so the agent can write
``output/``. This only works on the docker provider: the sandbox handle must
carry ``metadata['container_name']``.

Unlike ``baked_in_sandbox`` (which decrypts a ``reference.7z``), the reference
tree here is already plaintext, so it is copied as-is into ``reference/``.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ...base_interface import SandboxHandle, TaskDataSpec
from . import join, task_subdir

logger = logging.getLogger(__name__)

# Container user that runs the cua-server / task code on ale-kasm (uid:gid).
_CONTAINER_OWNER = "1000:1000"


def _host_root(source: str) -> Path:
    root = source[len("local://"):]
    return Path(root).expanduser().resolve()


def _container(sandbox: SandboxHandle) -> str:
    name = (sandbox.metadata or {}).get("container_name")
    if not name:
        raise RuntimeError(
            "task_data_source=local:// requires the docker provider "
            "(sandbox.metadata['container_name'] missing)"
        )
    return str(name)


async def _docker(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _exec_root(container: str, *cmd: str) -> tuple[int, str, str]:
    return await _docker("exec", "-u", "root", container, *cmd)


async def _cp_into(container: str, host_dir: Path, remote_dir: str) -> None:
    """Copy ``host_dir`` (a directory) to ``remote_dir`` inside the container."""
    parent = remote_dir.rsplit("/", 1)[0] or "/"
    rc, _, err = await _exec_root(container, "mkdir", "-p", parent)
    if rc != 0:
        raise RuntimeError(f"mkdir {parent} in {container} failed: {err[:200]}")
    # `docker cp <dir> container:<remote_dir>` places the dir AT remote_dir.
    rc, _, err = await _docker("cp", str(host_dir), f"{container}:{remote_dir}")
    if rc != 0:
        raise RuntimeError(f"docker cp {host_dir} -> {container}:{remote_dir} failed: {err[:200]}")


async def stage_input(
    sandbox: SandboxHandle, task_data: TaskDataSpec, *, source: str,
) -> dict[str, Any]:
    container = _container(sandbox)
    root = _host_root(source)
    base = task_subdir(sandbox, task_data)
    rel = f"{task_data.domain_name}/{task_data.task_name}/{task_data.variant_name}"
    host_task = root / "data" / "tasks" / rel

    rc, _, err = await _exec_root(container, "mkdir", "-p", base)
    if rc != 0:
        raise RuntimeError(f"mkdir {base} failed: {err[:200]}")

    staged: list[str] = []
    for sub in ("input", "software"):
        host_sub = host_task / sub
        if not host_sub.is_dir():
            continue
        await _cp_into(container, host_sub, join(sandbox, base, sub))
        if sub == "software":
            await _exec_root(
                container, "bash", "-lc",
                f"find {join(sandbox, base, 'software')} -type f -exec chmod +x {{}} +",
            )
        staged.append(sub)

    if "input" not in staged:
        raise RuntimeError(
            f"task_data_source=local://: no input dir at {host_task / 'input'}"
        )

    await _exec_root(container, "mkdir", "-p", join(sandbox, base, "output"))
    await _exec_root(container, "chown", "-R", _CONTAINER_OWNER, base)
    return {"staged": staged, "source": source}


async def stage_reference(
    sandbox: SandboxHandle, task_data: TaskDataSpec, *, source: str,
) -> dict[str, Any]:
    container = _container(sandbox)
    root = _host_root(source)
    base = task_subdir(sandbox, task_data)
    rel = f"{task_data.domain_name}/{task_data.task_name}/{task_data.variant_name}"
    host_ref = root / "reference" / "tasks" / rel / "reference"

    if not host_ref.is_dir():
        return {"skipped": True, "reason": "no_local_reference"}

    target = join(sandbox, base, "reference")
    await _exec_root(container, "rm", "-rf", target)
    await _cp_into(container, host_ref, target)
    await _exec_root(container, "chown", "-R", _CONTAINER_OWNER, target)
    await _exec_root(container, "chmod", "-R", "777", target)
    return {"staged": ["reference"], "source": source}
