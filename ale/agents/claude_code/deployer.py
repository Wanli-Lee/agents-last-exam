"""ClaudeCodeDeployer — claude-code CLI runs INSIDE the eval VM.

**Phase 2 STUB**. Satisfies the new :class:`BaseAgentDeployer` signature
so factory validation / lifecycle dispatch work end-to-end, but actual
install/launch/parse_artifacts raise NotImplementedError until Phase 3
lands ``VmExecutor`` + we rewrite the body to use stdlib subprocess
(replacing the old ``session.run_command`` pattern). Legacy code is
preserved at ``deployer_legacy.py`` as Phase 3 reference.

When the deployer runs (Phase 3+ via VmExecutor), it lives **inside the
test VM's Python process** (shipped via cua python_exec). So
``self.runtime.work_dir`` is a VM-local path, ``subprocess.run("npm i ...")``
runs locally on the VM, and ``open("/home/user/.ale/.../prompt.txt", "w")``
writes to VM fs. No ``session`` object is needed — the deployer IS in
the VM.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from ale.agents.base import (
    AgentRunResult,
    BaseAgentConfig,
    BaseAgentDeployer,
)
from ale.agents.trajectory import TrajectoryBuilder

from .config import ClaudeCodeConfig

logger = logging.getLogger(__name__)


class ClaudeCodeDeployer(BaseAgentDeployer):
    """In-VM deployer for the @anthropic-ai/claude-code CLI.

    Only `runtime: vm` is supported — the CLI MUST live in the test VM
    fs to operate on the eval files. Factory validates this; yaml
    `runtime: docker` or `runtime: local` will be rejected at spec-load.
    """

    supported_runtimes: ClassVar[frozenset[str]] = frozenset({"vm"})

    @property
    def version(self) -> str | None:
        cfg: ClaudeCodeConfig = self.config  # type: ignore[assignment]
        return cfg.cli_version

    async def install(self) -> None:
        """Stage Node + claude CLI + MCP server in the VM.

        Phase 3: rewrite the old ``deployer_legacy.py`` install body
        using stdlib subprocess (substitute for the old
        ``session.run_command``). Path conventions come from
        ``self.runtime`` (VmRuntime adds image-baked path fields).
        """
        raise NotImplementedError(
            "ClaudeCodeDeployer.install — Phase 3 (VmExecutor) lands the "
            "subprocess-based rewrite; see deployer_legacy.py for the "
            "session-based body we'll port from."
        )

    async def launch(self, prompt: str) -> AgentRunResult:
        """Spawn claude CLI in the VM, poll done.marker, classify outcome.

        Phase 3: subprocess.Popen with setsid (Linux) / CREATE_NEW_PROCESS_GROUP
        (Windows); write done.marker on exit; poll from this same Python
        function until done or timeout_s elapsed.
        """
        raise NotImplementedError(
            "ClaudeCodeDeployer.launch — Phase 3 (VmExecutor) impl pending."
        )

    @classmethod
    def parse_artifacts(
        cls,
        *,
        work_dir: Path,
        config: BaseAgentConfig,
        run_result: AgentRunResult,
        builder: TrajectoryBuilder,
    ) -> None:
        """Parse the claude CLI's stream-json transcript → ATIF Steps.

        Phase 3: port _consume_assistant / _consume_user from
        deployer_legacy.py.
        """
        raise NotImplementedError(
            "ClaudeCodeDeployer.parse_artifacts — Phase 3 port pending."
        )
