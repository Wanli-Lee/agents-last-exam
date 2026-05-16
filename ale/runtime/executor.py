"""Executor ABC — strategy for placing + running a deployer in a runtime.

One Executor per runtime kind (``local`` / ``vm`` / ``docker``). The
lifecycle picks the executor by spec.runtime, hands it the deployer
class + runtime context, and calls :meth:`run_deployer` to execute and
:meth:`gather_to_host` to materialize the work_dir locally for parsing.

This file only declares the ABC + the registry. Concrete impls live
in sibling files (``local_executor.py``, ``vm_executor.py``,
``docker_executor.py``).
"""
from __future__ import annotations

import abc
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ale.agents.base import AgentRunResult, BaseAgentDeployer

    from .base import AgentRuntime


RuntimeKind = Literal["vm", "local", "docker"]


class Executor(abc.ABC):
    """One executor per runtime kind. Stateless — instance per run unit."""

    kind: RuntimeKind

    @abc.abstractmethod
    async def run_deployer(
        self,
        *,
        deployer_cls: type["BaseAgentDeployer"],
        runtime: "AgentRuntime",
        prompt: str,
        timeout_s: float,
    ) -> "AgentRunResult":
        """Place the deployer in the runtime's substrate, await install + launch.

        - LocalExecutor: ``deployer = deployer_cls(runtime); await install();
                         await launch(prompt)`` in this process.
        - VmExecutor:    scp the agent subtree to the VM, then ``cua.python_exec``
                         a bootstrap that constructs deployer + awaits lifecycle.
        - DockerExecutor: ``docker run`` with bind mounts; container entrypoint
                          does the same construct + await.

        Returns the :class:`AgentRunResult` from the deployer's launch.
        """

    @abc.abstractmethod
    async def gather_to_host(
        self,
        runtime: "AgentRuntime",
        *,
        dest: Path,
    ) -> Path:
        """Materialize the work_dir to ``dest`` on the framework host.

        Returns the local path that ``parse_artifacts`` should read from.

        - LocalExecutor: no-op (work_dir is already on host); return runtime.work_dir.
        - DockerExecutor: no-op (work_dir is bind-mounted); return host path.
        - VmExecutor: ``mirror.pull_dir(session, vm_work_dir, dest)``; return dest.
        """


# =============================================================================
# Registry — yaml `runtime: <key>` resolves to an Executor instance here
# =============================================================================

EXECUTORS: dict[str, Executor] = {}
"""Registry populated by each executor module's import-time
``EXECUTORS[<kind>] = <Executor>()``. Lifecycle does
``EXECUTORS[spec.runtime].run_deployer(...)``."""
