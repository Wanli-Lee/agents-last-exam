"""LocalExecutor — substrate is the framework's host process.

``run_command`` shells out via :mod:`asyncio.subprocess`; ``write_file``
/ ``read_file`` are direct filesystem ops. ``work_dir`` is a host path
identical to ``host_artifacts_dir`` (no gather step needed).

For agents whose process lifecycle is "spawn a CLI on the host",
``spawn_detached`` uses ``asyncio.create_subprocess_exec(...,
start_new_session=True)`` so the child outlives this RPC call.

Eval VM is reached through :attr:`sandbox.endpoint` — deployers that
need a cua session open it themselves (this Executor does not own one).
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Iterable

from ..base_interface import BaseExecutor

logger = logging.getLogger(__name__)


@dataclass
class LocalExecutor(BaseExecutor):
    """In-process host substrate — deployer is framework-host Python."""

    kind: ClassVar[str] = "local"

    # Maps PID → asyncio.subprocess.Process so wait_marker can do a
    # cheaper liveness check than ``os.kill(pid, 0)`` and so the
    # subprocess object's transport stays alive for the run.
    _spawned: dict[int, asyncio.subprocess.Process] = field(
        default_factory=dict, init=False, repr=False,
    )

    def _is_linux(self) -> bool:
        return platform.system() != "Windows"

    # ──────── filesystem primitives ────────

    async def run_command(
        self, command: str, *, timeout: float = 60,
    ) -> subprocess.CompletedProcess:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return subprocess.CompletedProcess(
                args=command, returncode=-1, stdout="", stderr="timeout",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    async def write_file(self, path: str, content: str | bytes) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            await asyncio.to_thread(p.write_bytes, content)
        else:
            await asyncio.to_thread(p.write_text, content, encoding="utf-8")

    async def read_file(self, path: str) -> bytes:
        p = Path(path)
        if not p.exists():
            return b""
        return await asyncio.to_thread(p.read_bytes)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(Path(path).exists)

    async def mkdir(self, path: str) -> None:
        await asyncio.to_thread(
            lambda: Path(path).mkdir(parents=True, exist_ok=True),
        )

    async def rm(self, paths: Iterable[str]) -> None:
        def _rm() -> None:
            for p in paths:
                pth = Path(p)
                if pth.is_dir() and not pth.is_symlink():
                    shutil.rmtree(pth, ignore_errors=True)
                else:
                    try:
                        pth.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        logger.debug("rm %s: %s", p, e)
        await asyncio.to_thread(_rm)

    async def list_dir(self, path: str) -> list[dict[str, Any]]:
        base = Path(path)
        if not base.exists():
            return []
        out: list[dict[str, Any]] = []
        for child in base.rglob("*"):
            rel = str(child.relative_to(base))
            out.append({
                "relpath": rel,
                "is_dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else 0,
            })
        return out

    # ──────── process-lifecycle primitives ────────

    async def spawn_detached(
        self,
        *,
        script_body: str,
        script_path: str,
        pid_file: str,
        reset_files: list[str] | None = None,
    ) -> int:
        if reset_files:
            await self.rm(reset_files)
        await self.write_file(script_path, script_body)
        if self._is_linux():
            await asyncio.to_thread(lambda: os.chmod(script_path, 0o755))
            argv: list[str] = ["bash", script_path]
        else:
            argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", script_path]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,  # detach from this process group
        )
        self._spawned[proc.pid] = proc
        # Persist PID to disk too — keeps parity with SandboxExecutor semantics
        # (deployer + tests may read pid_file directly).
        Path(pid_file).write_text(str(proc.pid))
        return proc.pid

    async def wait_marker(
        self,
        marker_path: str,
        *,
        pid: int,
        timeout: float,
        poll_interval: float = 5.0,
    ) -> tuple[str, int | None]:
        marker = Path(marker_path)
        deadline = time.monotonic() + timeout
        proc = self._spawned.get(pid)
        while True:
            if marker.exists():
                raw = marker.read_text().strip()
                try:
                    exit_code: int | None = int(raw) if raw else None
                except ValueError:
                    exit_code = None
                status = "completed" if exit_code == 0 else "failed"
                return status, exit_code
            # liveness
            alive = await self._alive(pid, proc)
            if not alive:
                return "crashed", None
            if time.monotonic() >= deadline:
                return "timeout", None
            await asyncio.sleep(poll_interval)

    async def _alive(
        self, pid: int, proc: asyncio.subprocess.Process | None,
    ) -> bool:
        if proc is not None and proc.returncode is None:
            # asyncio.subprocess.Process tracks its own state cheaply.
            return True
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but in different uid; treat as alive

    async def kill_process(self, pid: int) -> None:
        proc = self._spawned.get(pid)
        try:
            if proc is not None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            else:
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(2)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except ProcessLookupError:
            pass
