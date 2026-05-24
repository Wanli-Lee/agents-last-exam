"""BaseExecutor — substrate adapter providing the minimal I/O + process
primitives a deployer needs to do its work.

Three concrete subclasses (in :mod:`ale_run.executors`):

* :class:`SandboxExecutor`     — substrate is a remote cua-server VM;
                            primitives go over HTTP RPC
* :class:`LocalExecutor`  — substrate is the framework's own Python
                            process / host shell
* :class:`DockerExecutor` — substrate is a host docker container;
                            primitives via ``docker exec``

Each Executor is the per-unit context the deployer reads (work_dir,
sandbox, env, config) AND the I/O surface it acts through. The
deployer ALWAYS runs on the framework host — only the I/O calls cross
the substrate boundary.

Naming note: ``Executor`` here = **where the deployer's I/O lands**,
NOT to the OpenEnv ``Environment`` (the task world the agent acts on,
with reset/step semantics). The two coincide physically for ``vm``
mode but are conceptually distinct.

Surface
-------

Filesystem primitives:

  ``run_command`` / ``write_file`` / ``read_file`` / ``exists`` /
  ``mkdir`` / ``rm`` / ``list_dir``

  Plus a derived convenience: ``read_text``.

Process-lifecycle primitives:

  ``spawn_detached`` — write a script + launch it detached,
                       return the OS PID
  ``wait_marker``    — poll a done-marker file while watching process
                       liveness; return ``(status, exit_code)``
  ``kill_process``   — TERM + KILL; idempotent

That's it. 10 abstract methods, 1 derived helper. Each Executor MUST
implement all 10. Anything broader (URL fetch, cua session, agent
image path conventions) belongs to the deployer or to ``SandboxHandle``,
NOT here.
"""
from __future__ import annotations

import abc
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Iterable

from .sandbox import SandboxHandle

# Forward refs are inlined where needed; no TYPE_CHECKING block to avoid
# import-cycle confusion.


@dataclass
class BaseExecutor(abc.ABC):
    """Per-unit substrate adapter. Constructed once per run by the lifecycle."""

    # ──────── context (data fields) ────────

    # ``config`` is the resolved per-agent config (claude_code → ClaudeCodeConfig).
    # Type annotated as ``Any`` to avoid importing BaseAgentConfig here (it lives
    # in agent_deployer.py and would create an interface-layer cycle).
    config: Any

    work_dir: str
    """Substrate-native scratch dir owned by this run. POSIX or Windows-
    style depending on :attr:`sandbox.os`. Always a string — wrap in
    :class:`Path` on the host side when needed."""

    host_artifacts_dir: Path
    """Host-side path where artifacts end up after the lifecycle's gather.
    For Local/Docker this is the same as ``work_dir``; for Vm it's a
    separate directory the lifecycle gathers into."""

    sandbox: SandboxHandle
    """Post-provision reference to the compute env this unit runs against.
    Always set — every benchmark target is a live env."""

    env: dict[str, str] = field(default_factory=dict)
    """Env vars the framework wants injected into the agent process
    (api keys, base URLs). Deployers fold these into the launch shell."""

    kind: ClassVar[str] = ""
    """Subclass-supplied. Matches yaml ``executor: <kind>`` values."""

    # ──────── filesystem primitives ────────

    @abc.abstractmethod
    async def run_command(
        self, command: str, *, timeout: float = 60,
    ) -> subprocess.CompletedProcess:
        """Run a shell command on the substrate. Always returns a
        ``CompletedProcess`` (never raises on non-zero rc — caller checks
        ``.returncode``). On transport failure: rc=-1, stderr describes."""

    @abc.abstractmethod
    async def write_file(self, path: str, content: str | bytes) -> None:
        """Write ``content`` to ``path`` on the substrate. Overwrites.
        Binary-safe (base64 path for Windows)."""

    @abc.abstractmethod
    async def read_file(self, path: str) -> bytes:
        """Read ``path`` as bytes. Empty bytes on missing file or transport
        error — caller checks :meth:`exists` first if the distinction
        matters."""

    @abc.abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abc.abstractmethod
    async def mkdir(self, path: str) -> None:
        """Create ``path`` and any missing parents. Idempotent."""

    @abc.abstractmethod
    async def rm(self, paths: Iterable[str]) -> None:
        """Best-effort remove. Never raises on missing files."""

    @abc.abstractmethod
    async def list_dir(self, path: str) -> list[dict[str, Any]]:
        """Recursive directory walk. Returns a flat list of entries; each:

            ``{"relpath": "<path-from-base>", "is_dir": bool, "size": int}``

        ``relpath`` uses the substrate's native separator. Returns
        ``[]`` on missing directory or transport error."""

    async def read_text(self, path: str) -> str:
        """UTF-8 decode of :meth:`read_file`. The one derived helper."""
        return (await self.read_file(path)).decode("utf-8", errors="replace")

    # ──────── process lifecycle primitives ────────

    @abc.abstractmethod
    async def spawn_detached(
        self,
        *,
        script_body: str,
        script_path: str,
        pid_file: str,
        reset_files: list[str] | None = None,
    ) -> int:
        """Write ``script_body`` to ``script_path``, mark it executable
        if needed, spawn it detached, wait until the launcher writes the
        child PID to ``pid_file``, return that PID.

        ``script_body`` is the agent-specific shell/PS script. The
        executor wraps it in a launcher that:
          - removes ``reset_files`` (if any) before spawn
          - daemonizes (setsid / Start-Process / docker exec -d) so the
            child outlives the RPC call
          - writes its child PID to ``pid_file``

        The script MUST be self-contained: own stdout/stderr redirects,
        own done-marker write. The executor never touches its body."""

    @abc.abstractmethod
    async def wait_marker(
        self,
        marker_path: str,
        *,
        pid: int,
        timeout: float,
        poll_interval: float = 5.0,
    ) -> tuple[str, int | None]:
        """Poll ``marker_path`` until it appears, while also checking
        that the PID is still alive.

        Returns ``(status, exit_code)``:

          ``("completed", 0)``   — marker shows rc == 0
          ``("failed", rc)``     — marker shows rc != 0
          ``("crashed", None)``  — process gone before marker appeared
          ``("timeout", None)``  — deadline hit, marker never appeared

        Caller decides whether to kill the PID on timeout (typically
        yes — see :meth:`kill_process`)."""

    @abc.abstractmethod
    async def kill_process(self, pid: int) -> None:
        """Send TERM, wait 2 s, send KILL. Idempotent — does not raise
        if the process is already gone."""
