"""Test bootstrap shims for optional native dependencies.

The CUA ``agent`` package (cua-agent) imports optional MLX adapters at module
import time. On non-Apple hosts that native import path can abort the
interpreter during pytest collection, even though these unit tests never
exercise MLX. Stub the modules early so package import stays pure-Python.

Ported from agenthle-base/tests/conftest.py (harness provenance:
``openclaw-cua@a830cae2``); unchanged except this docstring.
"""

from __future__ import annotations

import sys
import types
from importlib.machinery import ModuleSpec


def _install_mlx_stubs() -> None:
    if "mlx" in sys.modules:
        return

    mlx_pkg = types.ModuleType("mlx")
    mlx_core = types.ModuleType("mlx.core")
    mlx_pkg.core = mlx_core
    mlx_pkg.__spec__ = ModuleSpec("mlx", loader=None)
    mlx_core.__spec__ = ModuleSpec("mlx.core", loader=None)

    mlx_vlm_pkg = types.ModuleType("mlx_vlm")
    mlx_vlm_pkg.generate = lambda *args, **kwargs: None
    mlx_vlm_pkg.load = lambda *args, **kwargs: (_StubObject(), _StubObject())
    mlx_vlm_pkg.__spec__ = ModuleSpec("mlx_vlm", loader=None)

    mlx_vlm_prompt_utils = types.ModuleType("mlx_vlm.prompt_utils")
    mlx_vlm_prompt_utils.apply_chat_template = lambda *args, **kwargs: ""
    mlx_vlm_prompt_utils.__spec__ = ModuleSpec("mlx_vlm.prompt_utils", loader=None)

    mlx_vlm_utils = types.ModuleType("mlx_vlm.utils")
    mlx_vlm_utils.load_config = lambda *args, **kwargs: {}
    mlx_vlm_utils.__spec__ = ModuleSpec("mlx_vlm.utils", loader=None)

    sys.modules["mlx"] = mlx_pkg
    sys.modules["mlx.core"] = mlx_core
    sys.modules["mlx_vlm"] = mlx_vlm_pkg
    sys.modules["mlx_vlm.prompt_utils"] = mlx_vlm_prompt_utils
    sys.modules["mlx_vlm.utils"] = mlx_vlm_utils


class _StubObject:
    pass


_install_mlx_stubs()
