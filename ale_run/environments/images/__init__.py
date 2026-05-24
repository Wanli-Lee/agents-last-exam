"""Logical image-family registry.

Each module under this package declares an :class:`Image` describing
one image family the framework knows how to provision against:

* identity (``name``, ``os``)
* VM-side path conventions (``work_dir_base`` / ``data_dir`` / ``node``
  / ``python`` / ``mcp_server_dir``) — splatted into
  :class:`SandboxHandle`
* provisioning defaults (``default_machine_type`` / ``gpu``) — read
  by Providers when sizing the substrate. Boot disk size comes from
  the underlying image itself; task data lives on the boot disk.

This is the framework's view of an image (what the deployer can rely
on without runtime discovery). The Provider-side, GCP-flavored
``GcloudImageSpec`` in :mod:`environments.capacity` is a different
concept — that one is per-deployment yaml config (zone, project,
network, image_name, ...).

Adding a new family = add a module here, declare ``IMAGE = Image(...)``,
register in ``_REGISTRY``. SandboxHandle / Providers / deployers never
hard-code an image-family literal — they consult :func:`get` /
:func:`registered`.

Currently two families:

  ``ale-ubuntu22``  — linux
  ``ale-win10``     — windows
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


OS = Literal["linux", "windows"]


@dataclass(frozen=True)
class Image:
    """One logical image family — paths + provisioning defaults."""

    # ─── identity ───
    name: str                    # registry key, e.g. "ale-ubuntu22"
    os: OS

    # ─── sandbox-side paths (splatted into SandboxHandle) ───
    work_dir_base: str
    """Per-run scratch root, e.g. ``/home/user/.ale``."""

    task_data_root: str
    """Where staged task data lives (input/, reference/, output/, ...).
    e.g. ``/media/user/data/ale-data`` (linux) / ``E:\\ale-data`` (windows).
    Convention used by ``data_staging`` to build
    ``<task_data_root>/<domain>/<task>/<variant>/<subdir>``."""

    node: str
    python: str
    mcp_server_dir: str

    # ─── provisioning defaults (consumed by Providers) ───
    default_machine_type: str
    gpu: str | None = None

    def sandbox_paths(self) -> dict[str, str]:
        """Field dict for ``SandboxHandle(**image.sandbox_paths(), ...)``."""
        return {
            "work_dir_base":  self.work_dir_base,
            "task_data_root": self.task_data_root,
            "node":           self.node,
            "python":         self.python,
            "mcp_server_dir": self.mcp_server_dir,
        }


# Registry — late imports avoid circular if a family module wants to
# reference Image (which it does via from-import).
from .ale_ubuntu22 import IMAGE as _ALE_UBUNTU22
from .ale_win10 import IMAGE as _ALE_WIN10


_REGISTRY: dict[str, Image] = {
    _ALE_UBUNTU22.name: _ALE_UBUNTU22,
    _ALE_WIN10.name: _ALE_WIN10,
}


def get(name: str) -> Image:
    """Look up an image family by name. Raise on unknown."""
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown image family {name!r}; "
            f"registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def registered() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["Image", "OS", "get", "registered"]
