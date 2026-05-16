"""AgentRuntime — passive context injected into a deployer at init.

This is **data, not API**. Deployer code uses stdlib (subprocess, pathlib,
json) for execution; ``self.runtime`` only tells it WHERE things live
(work_dir, the eval VM's endpoint) and WHAT to use as config.

The ONE method on this base — :meth:`make_vm_session` — is a convenience
constructor so deployers don't reimplement the same RemoteDesktopSession
boilerplate three times.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

if TYPE_CHECKING:
    import cua_bench as cb

    from ale.agents.base import BaseAgentConfig


RuntimeKind = Literal["vm", "local", "docker"]


@dataclass
class AgentRuntime:
    """The runtime context a deployer is constructed with.

    Subclasses (:class:`LocalRuntime`, :class:`VmRuntime`,
    :class:`DockerRuntime`) only add per-runtime conventions
    (parent dirs, image-baked binary paths) — same data shape.
    """

    # ---- universal context ----
    work_dir: Path
    """Scratch dir the deployer owns for this run. Convention depends on
    the runtime kind (see subclass docstrings)."""

    vm_endpoint: str
    """cua-server URL of the eval VM, e.g. ``http://34.94.212.100:5000``.
    The deployer constructs its own session against this if it needs to
    drive the VM (ale_claw style). claude_code-style agents that run
    INSIDE the VM don't need it (they use subprocess locally)."""

    vm_os: Literal["linux", "windows"]
    """OS of the eval VM. Used for cross-OS code dispatch in deployers
    that care (e.g. setsid on Linux vs Start-Process on Windows)."""

    config: "BaseAgentConfig"
    """Deployer's bound config. Same object passed at runtime construction
    so the deployer can read its tunables (model, max_turns, api keys, ...)
    via ``self.runtime.config`` or the convenience alias ``self.config``."""

    kind: ClassVar[RuntimeKind] = "local"
    """ClassVar set by each subclass — matches the yaml ``runtime`` value."""

    # ---- the one method ----

    async def make_vm_session(self) -> "cb.DesktopSession":
        """Construct a fresh :class:`cb.DesktopSession` against the eval VM.

        Used by host-side deployers (ale_claw etc.) that drive the VM via
        RPC. Each call returns a fresh session — multiple concurrent
        sessions to the same cua-server are safe (the server is stateless
        for our usage).

        VM-side deployers (claude_code) don't need this — they're IN the
        VM and use stdlib subprocess directly. Calling this from a
        VmRuntime returns a loopback session, which works but is wasteful.
        """
        from cua_bench.computers.remote import RemoteDesktopSession

        session = RemoteDesktopSession(
            api_url=self.vm_endpoint,
            os_type=self.vm_os,
            ephemeral=False,           # VM lifecycle is owned by ALE's Provider
            headless=True,
        )
        await session.check_status()    # initialize the underlying Computer SDK
        return session
