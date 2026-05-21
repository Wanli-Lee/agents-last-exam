"""Shared deployer base classes — one per agent distribution model.

Four bases, organised by **how the agent's executable reaches the
substrate**:

* :class:`PrebakedRemoteCliDeployer` — agent CLI is already baked into
  the VM image. ``install`` just probes it. (ClaudeCode.)
* :class:`FetchingRemoteCliDeployer` — agent CLI is fetched into the
  substrate at install time via a small DSL (``npm:`` / ``pip:`` /
  ``url:``). ``install`` dispatches, then probes.
* :class:`InHostDeployer` — agent is a Python module imported by
  the framework. ``install`` does import + env sanity checks.
  (AleClaw on ``local`` or ``docker`` runtime.)
* :class:`InDockerDeployer` — agent is shipped AS a docker image
  (NOT the same as the framework-in-docker case, which is
  ``InHostDeployer`` + ``DockerRuntime``). **Shell.**

Plus :class:`RemoteCliDeployer` — the shared parent of the two remote-CLI
bases. Holds the spawn / poll / kill / probe helpers; intentionally has
no ``install`` because the two subclasses install differently.
"""
from __future__ import annotations

from .in_docker import InDockerDeployer
from .in_host import InHostDeployer
from .remote_cli import (
    FetchingRemoteCliDeployer,
    PrebakedRemoteCliDeployer,
    RemoteCliDeployer,
)

__all__ = [
    "InDockerDeployer",
    "FetchingRemoteCliDeployer",
    "InHostDeployer",
    "PrebakedRemoteCliDeployer",
    "RemoteCliDeployer",
]
