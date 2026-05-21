"""``base_interface`` — every settled contract the framework agrees on.

This package has **zero internal dependencies**: it imports only stdlib,
pydantic, and openenv. Every other top-level layer (``agents/``,
``environments/``, ``tasks/``, ``orchastration/``) depends on it; nothing
in those layers cross-references each other's internals.

Contents:

* :class:`BaseAgentDeployer`, :class:`BaseAgentConfig`,
  :class:`AgentRunResult`, :class:`EpisodeResult` — agent contract.
* :class:`BaseRuntime` — substrate adapter contract.
* :class:`Provider`, :class:`EnvSpec`, :class:`EnvHandle`,
  :data:`ReleaseMode` — compute-env provisioning contract (VMs,
  containers, anything that speaks cua-server HTTP).
* :class:`TaskDataSpec` — task data-staging contract.
* :class:`Trajectory`, :class:`TrajectoryBuilder`, :class:`Step`,
  :class:`ToolCall`, :class:`ToolResult`, :class:`Observation`,
  :class:`StepMetrics`, :class:`FinalMetrics`, :class:`AgentInfo`,
  :class:`ContentPart`, :class:`ImageSource` — ATIF trajectory format.

The only intra-package coupling is the ``BaseAgentDeployer`` ↔
``BaseRuntime`` reference, which both files manage via TYPE_CHECKING.
Outside ``base_interface/`` the cycle is invisible.
"""
from __future__ import annotations

from .agent_deployer import (
    AgentRunResult,
    BaseAgentConfig,
    BaseAgentDeployer,
    EpisodeResult,
)
from .agent_runtime import BaseRuntime
from .compute_env import (
    EnvHandle,
    EnvSpec,
    OS,
    Provider,
    ReleaseMode,
)
from .task_data import TaskDataSpec
from .trajectory import (
    AgentInfo,
    ContentPart,
    FinalMetrics,
    ImageSource,
    Observation,
    SCHEMA_VERSION,
    Source,
    Step,
    StepMetrics,
    ToolCall,
    ToolResult,
    Trajectory,
    TrajectoryBuilder,
)

__all__ = [
    # agent_deployer.py
    "AgentRunResult",
    "BaseAgentConfig",
    "BaseAgentDeployer",
    "EpisodeResult",
    # agent_runtime.py
    "BaseRuntime",
    # compute_env.py
    "EnvHandle",
    "EnvSpec",
    "OS",
    "Provider",
    "ReleaseMode",
    # task_data.py
    "TaskDataSpec",
    # trajectory.py
    "AgentInfo",
    "ContentPart",
    "FinalMetrics",
    "ImageSource",
    "Observation",
    "SCHEMA_VERSION",
    "Source",
    "Step",
    "StepMetrics",
    "ToolCall",
    "ToolResult",
    "Trajectory",
    "TrajectoryBuilder",
]
