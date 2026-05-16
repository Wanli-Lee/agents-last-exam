"""Build Provider / Agent instances from spec dataclasses.

The registries below are the canonical way to add a new provider or agent
to the experiment yaml surface. Shortcut → fqdn mapping keeps yamls short
without sacrificing the explicit ``module.Class`` form for new agents.

Agent construction in the new (post-Runtime-refactor) world is a two-step
process:

  1. :func:`resolve_agent_class` — turn spec.class_ into (DeployerCls, ConfigCls),
     pick the runtime kind (validating against ``DeployerCls.supported_runtimes``),
     and build the config dataclass from spec.config.
  2. The lifecycle (in :mod:`ale.runner.lifecycle`) then constructs the
     runtime (kind-specific) and finally ``deployer = DeployerCls(runtime)``.

We split that into two calls so the lifecycle can extract VM endpoint info
from the env *between* config-build and runtime-build.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ale.core.provider import Provider

from .spec import AgentSpec, ProviderSpec

if TYPE_CHECKING:
    from ale.agents.base import BaseAgentConfig, BaseAgentDeployer


# =============================================================================
# Provider registry — kind → (provider class, config class)
# =============================================================================

PROVIDER_REGISTRY: dict[str, tuple[str, str]] = {
    "gcs_direct": (
        "ale.providers.gcs_direct.GCSDirectProvider",
        "ale.providers.gcs_direct.GCSDirectConfig",
    ),
    "static": (
        "ale.providers.static.StaticProvider",
        "ale.providers.static.StaticProviderConfig",
    ),
}


def build_provider(spec: ProviderSpec) -> Provider:
    if spec.kind not in PROVIDER_REGISTRY:
        raise KeyError(
            f"unknown provider.kind={spec.kind!r}; "
            f"available: {sorted(PROVIDER_REGISTRY)}"
        )
    prov_path, cfg_path = PROVIDER_REGISTRY[spec.kind]
    prov_cls = _import_name(prov_path)
    cfg_cls = _import_name(cfg_path)
    try:
        cfg = cfg_cls(**spec.config)
    except TypeError as exc:
        raise TypeError(
            f"provider.kind={spec.kind!r} got bad config: {exc}; "
            f"check unknown / missing keys"
        ) from exc
    return prov_cls(cfg)


# =============================================================================
# Agent registry — shortcut → (deployer class, config class)
# =============================================================================

AGENT_REGISTRY: dict[str, tuple[str, str]] = {
    "claude_code": (
        "ale.agents.claude_code.deployer.ClaudeCodeDeployer",
        "ale.agents.claude_code.config.ClaudeCodeConfig",
    ),
    "ale_claw": (
        "ale.agents.ale_claw.deployer.AleClawDeployer",
        "ale.agents.ale_claw.config.AleClawConfig",
    ),
    # Add more here as deployers come online:
    # "codex": ("ale...CodexDeployer", "ale...CodexConfig"),
}


@dataclass
class ResolvedAgent:
    """What :func:`resolve_agent` returns — everything the lifecycle needs
    EXCEPT the runtime instance (which it constructs separately because
    the runtime needs VM endpoint info from env, not yet available here).
    """

    deployer_cls: type["BaseAgentDeployer"]
    config: "BaseAgentConfig"
    runtime_kind: str         # validated ∈ deployer_cls.supported_runtimes


def resolve_agent(spec: AgentSpec) -> ResolvedAgent:
    """Resolve ``spec`` into (deployer class, config instance, runtime kind).

    Pipeline:
      1. Import deployer + config classes (via :data:`AGENT_REGISTRY` shortcut
         or fqdn fallback).
      2. Build the config dataclass from ``spec.config`` kwargs.
      3. Pick a runtime: prefer ``spec.runtime`` if given (must be in
         ``deployer_cls.supported_runtimes``); else auto-pick:
            - if a single runtime is supported → use it
            - elif "local" is supported → use "local" (ergonomic default)
            - else → raise (ambiguous; user must specify)
    """
    if spec.class_ in AGENT_REGISTRY:
        dep_path, cfg_path = AGENT_REGISTRY[spec.class_]
        dep_cls = _import_name(dep_path)
        cfg_cls = _import_name(cfg_path)
    else:
        dep_cls = _import_name(spec.class_)
        cfg_cls = _infer_config_class(dep_cls)

    try:
        cfg = cfg_cls(**spec.config)
    except TypeError as exc:
        raise TypeError(
            f"agent id={spec.id!r} (class {spec.class_}) got bad config: {exc}"
        ) from exc

    supported = frozenset(getattr(dep_cls, "supported_runtimes", frozenset()))
    if not supported:
        raise TypeError(
            f"agent {dep_cls.__name__} declares no supported_runtimes; "
            f"every BaseAgentDeployer subclass must set this ClassVar."
        )

    if spec.runtime is None:
        runtime_kind = _auto_pick_runtime(supported, dep_cls.__name__, spec.id)
    else:
        if spec.runtime not in supported:
            raise ValueError(
                f"agent id={spec.id!r} (class {dep_cls.__name__}) configured "
                f"runtime={spec.runtime!r}, but the deployer only supports "
                f"{sorted(supported)}."
            )
        runtime_kind = spec.runtime

    return ResolvedAgent(deployer_cls=dep_cls, config=cfg, runtime_kind=runtime_kind)


def _auto_pick_runtime(supported: frozenset[str], dep_name: str, agent_id: str) -> str:
    """Default-runtime policy when spec.runtime is omitted.

    Rules:
      - len(supported) == 1: that one.
      - "local" supported: "local" (dev ergonomics — fast, no docker daemon).
      - else: raise; user must pick explicitly.
    """
    if len(supported) == 1:
        return next(iter(supported))
    if "local" in supported:
        return "local"
    raise ValueError(
        f"agent id={agent_id!r} (class {dep_name}) supports multiple runtimes "
        f"{sorted(supported)} but none is the conventional default; "
        f"set `runtime: <kind>` explicitly in the yaml."
    )


# ---- legacy shim so any callers still importing build_agent get a clear error ----

def build_agent(spec: AgentSpec):
    """Deprecated. Use :func:`resolve_agent` + construct runtime/deployer
    in lifecycle. Kept as a guardrail so old callers fail loudly."""
    raise RuntimeError(
        "build_agent() removed in the Runtime refactor. Use "
        "ale.runner.factory.resolve_agent(spec) and let lifecycle build the "
        "runtime + deployer."
    )


# =============================================================================
# Helpers
# =============================================================================

def _import_name(dotted_path: str) -> Any:
    """``"pkg.mod.Class"`` → the class object."""
    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(f"invalid import path: {dotted_path!r}")
    module = importlib.import_module(module_path)
    if not hasattr(module, attr):
        raise AttributeError(f"{module_path} has no attribute {attr!r}")
    return getattr(module, attr)


def _infer_config_class(deployer_cls: type) -> type:
    """Pull the Config class out of the deployer's ``__init__(self, config: X)`` signature."""
    import inspect
    sig = inspect.signature(deployer_cls.__init__)
    if "config" not in sig.parameters:
        raise TypeError(
            f"{deployer_cls.__name__} has no 'config' parameter; "
            f"cannot infer Config class — register the shortcut explicitly."
        )
    ann = sig.parameters["config"].annotation
    if ann is inspect.Parameter.empty:
        raise TypeError(
            f"{deployer_cls.__name__}.__init__ has untyped 'config' parameter; "
            f"add type annotation or register the shortcut explicitly."
        )
    return ann
