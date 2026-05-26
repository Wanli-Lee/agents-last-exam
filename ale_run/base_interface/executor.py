"""BaseExecutor — substrate adapter that places + drives a deployer.

The framework recognises three Executor types (in :mod:`ale_run.executors`):

* :class:`LocalExecutor`   — run the deployer in the framework's own
                             Python process.
* :class:`DockerExecutor`  — ``docker run`` a fresh container per unit,
                             ship the deployer + ALE source into it,
                             entrypoint runs the deployer in-container.
* :class:`SandboxExecutor` — scp the ALE source to the sandbox VM,
                             ``cua.python_exec`` a bootstrap that runs
                             the deployer inside the sandbox itself.

What the executor IS to a deployer
----------------------------------

A passive data carrier. The deployer's ``__init__(executor)`` reads
``executor.work_dir / sandbox / config / env`` and operates with **Python
stdlib only** (``subprocess`` / ``pathlib`` / ``json`` / ``asyncio``).
The deployer never calls the three abstract methods below — those are
the **lifecycle's** handle on the substrate, not the deployer's.

What the executor IS to the lifecycle
-------------------------------------

Three methods:

* :meth:`run_deployer`   — place + run the deployer end-to-end;
                           return an :class:`AgentRunResult`.
* :meth:`gather_dir`     — bulk-pull ``src`` (substrate-native path)
                           into ``dst`` (host directory). No-op when
                           ``src`` is already a host path.
* :meth:`download_range` — incremental ranged read of a single file on
                           the substrate. Used by hot-artifact tailing.

Cross-OS deployer contract
--------------------------

The Sandbox executor's substrate may be linux OR windows (per
:attr:`SandboxHandle.os`). Deployer code is responsible for its own OS
dispatch using ``self.executor.sandbox.os``; the framework does not
abstract this.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TYPE_CHECKING

from .sandbox import RangeResult, SandboxHandle

if TYPE_CHECKING:
    from .agent_deployer import AgentRunResult, BaseAgentDeployer


@dataclass
class GatherReport:
    """Outcome of :meth:`BaseExecutor.gather_dir`.

    Always returned (never raised) so the lifecycle can log and proceed
    when transport hiccups. Empty/no-op pulls report ``files == 0``.
    """

    transport: str                # "local" | "docker-bindmount" | "cua"
    files: int = 0
    bytes: int = 0
    error: str | None = None


@dataclass
class BaseExecutor(abc.ABC):
    """Per-unit substrate adapter. Constructed once per run by the
    lifecycle; lives for the duration of one run unit.
    """

    # ──────── data fields (deployer reads these) ────────

    # Annotated as ``Any`` to avoid importing :class:`BaseAgentConfig`
    # here (it lives in ``agent_deployer`` and a real type would create
    # an interface-package cycle).
    config: Any
    """Per-agent resolved config (claude_code → ClaudeCodeConfig …).
    Concrete dataclass; deployer reads via ``self.config`` alias."""

    work_dir: str
    """Substrate-native scratch dir owned by this run. POSIX or Windows-
    style depending on :attr:`sandbox.os`. The deployer's
    transcript / stderr / done.marker land here."""

    sandbox: SandboxHandle
    """The cua-server eval target. Deployer reads ``sandbox.endpoint /
    .os / .work_dir_base / ...`` to talk to its evaluation environment.
    The Executor itself uses the handle internally for scp + cua RPC
    when the substrate IS the sandbox (SandboxExecutor)."""

    env: dict[str, str] = field(default_factory=dict)
    """Env vars the framework wants injected into the deployer's
    process (api keys, base URLs). The deployer folds these into its
    launched-agent shell."""

    type: ClassVar[str] = ""
    """Subclass-supplied discriminator. Matches yaml ``executor: <type>``
    values. Validated on concrete-subclass creation."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Concrete subclasses must set ``type``; intermediate abstract
        # bases (still carrying abstract methods) are skipped.
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "type", ""):
            raise TypeError(
                f"{cls.__name__}: concrete Executor subclass must set "
                "class attribute `type` to a non-empty string"
            )

    # ──────── methods (lifecycle uses these) ────────

    @abc.abstractmethod
    async def run_deployer(
        self,
        *,
        deployer_cls: type["BaseAgentDeployer"],
        prompt: str,
        timeout_s: float,
    ) -> "AgentRunResult":
        """Place + drive the deployer end-to-end on this substrate.

        Concrete implementations:

        * **LocalExecutor**: in-process construct + ``await install();
          await launch()``.
        * **DockerExecutor**: stage spec.json into the host bind-mount,
          ``docker run`` with an entrypoint that imports the deployer,
          constructs a local-flavored Executor inside the container,
          and runs it. Returns the container's ``_result.json``.
        * **SandboxExecutor**: scp the ``ale_run/`` tree into the
          sandbox, ``cua.python_exec`` a bootstrap that imports the
          deployer + constructs a local-flavored Executor in-sandbox
          and runs it. Returns the bootstrap's result dict.

        On crash inside the substrate, the implementation MUST surface
        the traceback in :attr:`AgentRunResult.error` (and pull any
        crash logs into the host's gather target if possible)."""

    @abc.abstractmethod
    async def gather_dir(
        self,
        *,
        src: str,
        dst: Path,
    ) -> GatherReport:
        """Recursively copy ``src`` (substrate-native path) into ``dst``
        (host directory; created if missing).

        No-op (``files=0``) when ``src`` is already a host path
        (LocalExecutor, DockerExecutor with bind mount). Best-effort —
        any per-file failure is logged but does not raise; the
        ``error`` field on the return value reports the first failure."""

    @abc.abstractmethod
    async def download_range(
        self,
        *,
        src: str,
        start: int,
        max_bytes: int,
    ) -> RangeResult:
        """Read ``[start, start+max_bytes)`` of ``src`` on the substrate.

        Returns a :class:`RangeResult` carrying the new bytes plus the
        current total file size (so callers can detect file truncation
        or rotation). Used by hot-artifact tailing (incremental sync of
        transcript.jsonl / stderr.log etc.) for sandbox runs; for local
        and docker runs the file IS on host and callers can just read
        directly — but the method is implemented uniformly so callers
        don't have to special-case substrate type."""
