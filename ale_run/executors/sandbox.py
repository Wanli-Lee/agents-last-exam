"""SandboxExecutor — the agent runs INSIDE the sandbox (cua-server VM).

In ``executor: vm`` mode, the executor's substrate IS the sandbox.
Every filesystem method just forwards to :class:`SandboxHandle`'s API
(one-liners). Process-lifecycle primitives (``spawn_detached`` /
``wait_marker`` / ``kill_process``) are bash/PowerShell scripts that
themselves run on the sandbox via ``self.sandbox.run_command``.

For ``executor: local`` / ``executor: docker``, the agent runs on a
different substrate than the sandbox — see :class:`LocalExecutor` /
:class:`DockerExecutor`.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable

from ..base_interface import BaseExecutor

logger = logging.getLogger(__name__)


@dataclass
class SandboxExecutor(BaseExecutor):
    """Forwards filesystem I/O to ``self.sandbox``; spawns processes on the
    sandbox itself."""

    kind: ClassVar[str] = "sandbox"

    # ──────── filesystem primitives — pure forwards ────────

    async def run_command(
        self, command: str, *, timeout: float = 60,
    ) -> subprocess.CompletedProcess:
        return await self.sandbox.run_command(command, timeout=timeout)

    async def write_file(self, path: str, content: str | bytes) -> None:
        await self.sandbox.write_file(path, content)

    async def read_file(self, path: str) -> bytes:
        return await self.sandbox.read_file(path)

    async def exists(self, path: str) -> bool:
        return await self.sandbox.exists(path)

    async def mkdir(self, path: str) -> None:
        await self.sandbox.mkdir(path)

    async def rm(self, paths: Iterable[str]) -> None:
        await self.sandbox.rm(paths)

    async def list_dir(self, path: str) -> list[dict[str, Any]]:
        return await self.sandbox.list_dir(path)

    # ──────── process-lifecycle primitives ────────

    async def spawn_detached(
        self,
        *,
        script_body: str,
        script_path: str,
        pid_file: str,
        reset_files: list[str] | None = None,
    ) -> int:
        """Stage ``script_body`` onto the sandbox, daemonize it, return the
        sandbox-local PID.

        Linux:   ``setsid bash <script>`` via launcher.sh that ``echo $!``
                 into pid_file.
        Windows: ``Start-Process -PassThru`` with ``$proc.Id | Out-File``
                 into pid_file.
        """
        sb = self.sandbox
        if reset_files:
            await sb.rm(reset_files)
        await sb.write_file(script_path, script_body)

        if sb.is_linux:
            await sb.run_command(
                f"chmod +x {shlex.quote(script_path)}", timeout=15,
            )
            launcher_path = script_path + ".launch"
            launcher = (
                "#!/bin/bash\n"
                f"setsid bash {shlex.quote(script_path)} "
                "</dev/null >/dev/null 2>&1 &\n"
                "CHILD=$!\n"
                f"echo \"$CHILD\" > {shlex.quote(pid_file)}\n"
                "disown $CHILD 2>/dev/null || true\n"
            )
            await sb.write_file(launcher_path, launcher)
            await sb.run_command(f"chmod +x {shlex.quote(launcher_path)}", timeout=15)
            result = await sb.run_command(
                f"bash {shlex.quote(launcher_path)}", timeout=30,
            )
        else:
            spawn_cmd = (
                'powershell -NoProfile -Command "'
                "$proc = Start-Process powershell "
                f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','{script_path}' "
                f"-WindowStyle Hidden -PassThru; "
                f"$proc.Id | Out-File -FilePath '{pid_file}' -Encoding ascii -NoNewline"
                '"'
            )
            result = await sb.run_command(spawn_cmd, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(
                f"spawn_detached failed rc={result.returncode}: "
                f"{(result.stderr or '').strip()[:300]}"
            )

        # Read PID. Launcher is synchronous so it's usually there immediately,
        # but tolerate a tiny flush gap.
        deadline = time.monotonic() + 4.5
        while time.monotonic() < deadline:
            if await sb.exists(pid_file):
                raw = (await sb.read_text(pid_file)).strip()
                try:
                    return int(raw)
                except ValueError:
                    break
            await asyncio.sleep(0.3)
        raise RuntimeError(
            f"spawn_detached: launcher did not write a usable PID to {pid_file}"
        )

    async def wait_marker(
        self,
        marker_path: str,
        *,
        pid: int,
        timeout: float,
        poll_interval: float = 5.0,
    ) -> tuple[str, int | None]:
        sb = self.sandbox
        deadline = time.monotonic() + timeout
        while True:
            if await sb.exists(marker_path):
                raw = (await sb.read_text(marker_path)).strip()
                try:
                    exit_code: int | None = int(raw) if raw else None
                except ValueError:
                    exit_code = None
                status = "completed" if exit_code == 0 else "failed"
                return status, exit_code
            # liveness check
            if sb.is_linux:
                alive = await sb.run_command(f"kill -0 {pid}", timeout=10)
            else:
                alive = await sb.run_command(
                    f'powershell -NoProfile -Command "Get-Process -Id {pid} -ErrorAction Stop | Out-Null"',
                    timeout=10,
                )
            if alive.returncode != 0:
                return "crashed", None
            if time.monotonic() >= deadline:
                return "timeout", None
            await asyncio.sleep(poll_interval)

    async def kill_process(self, pid: int) -> None:
        sb = self.sandbox
        if sb.is_linux:
            await sb.run_command(f"kill -TERM {pid}", timeout=15)
            await asyncio.sleep(2)
            await sb.run_command(f"kill -KILL {pid}", timeout=15)
        else:
            await sb.run_command(
                f'powershell -NoProfile -Command "Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"',
                timeout=15,
            )
