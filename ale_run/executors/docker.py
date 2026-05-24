"""DockerExecutor — substrate is a container on the host docker daemon.

Stub. Carries the image tag + container_id (set by lifecycle once
``docker run`` returns); all I/O dispatches via ``docker exec`` into
that container. ``work_dir`` is the container-local mount target;
``host_artifacts_dir`` is the host-side bind mount so artifacts flow
back without an explicit gather.

Implementation is deferred until the first concrete docker-bound
deployer needs it. Every primitive raises ``NotImplementedError`` with
a comment pointing at the docker invocation that would land here.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable

from ..base_interface import BaseExecutor

logger = logging.getLogger(__name__)


_STUB_MSG = (
    "DockerExecutor.%s: container dispatch not yet wired. "
    "Will be implemented alongside the first concrete docker-bound deployer."
)


@dataclass
class DockerExecutor(BaseExecutor):
    """In-container substrate. Not yet implemented."""

    image: str = ""
    """Image tag the container was started from (set by lifecycle)."""

    container_id: str = ""
    """``docker run`` ID. Empty until the lifecycle starts the container."""

    kind: ClassVar[str] = "docker"

    # ──────── filesystem primitives ────────

    async def run_command(
        self, command: str, *, timeout: float = 60,
    ) -> subprocess.CompletedProcess:
        raise NotImplementedError(_STUB_MSG % "run_command")

    async def write_file(self, path: str, content: str | bytes) -> None:
        raise NotImplementedError(_STUB_MSG % "write_file")

    async def read_file(self, path: str) -> bytes:
        raise NotImplementedError(_STUB_MSG % "read_file")

    async def exists(self, path: str) -> bool:
        raise NotImplementedError(_STUB_MSG % "exists")

    async def mkdir(self, path: str) -> None:
        raise NotImplementedError(_STUB_MSG % "mkdir")

    async def rm(self, paths: Iterable[str]) -> None:
        raise NotImplementedError(_STUB_MSG % "rm")

    async def list_dir(self, path: str) -> list[dict[str, Any]]:
        raise NotImplementedError(_STUB_MSG % "list_dir")

    # ──────── process-lifecycle primitives ────────

    async def spawn_detached(
        self,
        *,
        script_body: str,
        script_path: str,
        pid_file: str,
        reset_files: list[str] | None = None,
    ) -> int:
        raise NotImplementedError(_STUB_MSG % "spawn_detached")

    async def wait_marker(
        self,
        marker_path: str,
        *,
        pid: int,
        timeout: float,
        poll_interval: float = 5.0,
    ) -> tuple[str, int | None]:
        raise NotImplementedError(_STUB_MSG % "wait_marker")

    async def kill_process(self, pid: int) -> None:
        raise NotImplementedError(_STUB_MSG % "kill_process")
