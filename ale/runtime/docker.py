"""DockerRuntime — deployer code runs INSIDE a host docker container.

work_dir is ``/work`` *inside the container*. On the host, that's a
bind-mount of ``<run_dir>/origin_log/<agent>/`` so artifacts flow back
without any explicit gather copy.

The container shares the host's network (``--network host``) so it can
reach the eval VM's cua-server on its public IP.

When constructed inside the container (in :mod:`_docker_entry`), all
``self.runtime.*`` fields refer to container-local paths; container-side
ale code uses stdlib (subprocess, pathlib) the same way LocalRuntime
would on host.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .base import AgentRuntime, RuntimeKind


@dataclass
class DockerRuntime(AgentRuntime):
    """Host-docker runtime — agent lives in a container.

    Same shape as LocalRuntime — no extra fields. The container provides
    the isolation, mount paths are standardized (/work for artifacts,
    /projects for ale source), and the deployer is none the wiser.
    """

    kind: ClassVar[RuntimeKind] = "docker"
