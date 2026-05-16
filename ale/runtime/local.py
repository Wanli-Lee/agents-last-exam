"""LocalRuntime — deployer runs in this Python process.

Convention: ``work_dir = /tmp/ale/<agent_name>/<run_id>/``. No image
conventions needed (the host is whatever the user's machine is; deployer
declares its own deps in ``ale/agents/<agent>/pyproject.toml``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .base import AgentRuntime, RuntimeKind


@dataclass
class LocalRuntime(AgentRuntime):
    """In-process runtime — agent lives in the framework's Python process.

    No extra fields beyond :class:`AgentRuntime`. Constructed by
    :class:`LocalExecutor` with ``work_dir = /tmp/ale/<agent>/<run_id>``
    pre-created.
    """

    kind: ClassVar[RuntimeKind] = "local"
