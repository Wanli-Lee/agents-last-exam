"""AleClawConfig: per-episode knobs for the OpenClaw native agent deployer.

Inherits :class:`BaseAgentConfig` for the standard surface
(``model`` / ``max_turns`` / ``timeout_s`` / ``api_keys`` / ``install_paths``)
and adds OpenClaw-specific knobs below.

API keys are **never auto-read** from the environment — the caller passes
them explicitly. The deployer's :meth:`launch` will temporarily set them
into ``os.environ`` for the harness's litellm-driven LLM calls, then
restore on exit. ALE convention: don't let cross-experiment env-var bleed
sneak credentials into wrong runs.

Typical usage::

    import os
    cfg = AleClawConfig(
        model="openrouter/anthropic/claude-sonnet-4-20250514",
        openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        max_turns=100,
        timeout_s=3600,
    )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ale.agents.base import BaseAgentConfig


@dataclass
class AleClawConfig(BaseAgentConfig):
    """Tunables for :class:`AleClawDeployer`."""

    name: ClassVar[str] = "ale-claw"

    # ---- override base defaults ----
    model: str = "openrouter/anthropic/claude-sonnet-4.6"
    """LiteLLM-format model id. Maps to OpenClaw's ``model`` kwarg verbatim.
    OpenRouter routes work via the vendored ``unified_loop`` (registered for
    ``openrouter/.*`` regex)."""

    max_turns: int | None = 100
    """Mapped to OpenClaw's ``max_steps``. Hard ceiling on the agent run loop."""

    timeout_s: float = 3600.0
    """Wall-clock budget for the whole episode. Enforced via
    :func:`asyncio.wait_for` around the harness's ``agent.run`` loop."""

    # ---- routing / auth (caller passes explicitly; never read from os.environ) ----
    openrouter_api_key: str | None = None
    """When set, exported as ``OPENROUTER_API_KEY`` for the harness's litellm calls."""

    anthropic_api_key: str | None = None
    """When set, exported as ``ANTHROPIC_API_KEY`` for direct-Anthropic models."""

    openai_api_key: str | None = None
    """When set, exported as ``OPENAI_API_KEY`` for direct-OpenAI models."""

    brave_api_key: str | None = None
    """Required iff ``web_search`` is NOT in :attr:`disabled_tools`. Without it,
    the tool hard-fails on every call. Default config disables web_search so
    this can stay None."""

    # ---- model variants ----
    summary_model: str | None = None
    """Model for compaction + memory_flush. None → ``lightweight_model`` if set,
    else ``model``. Cheaper sibling for cost savings."""

    gui_model: str | None = None
    """Model for the ``delegate_gui`` subagent. None → ``lightweight_model``
    if set, else falls back to main."""

    lightweight_model: str | None = None
    """Optional cheap-sibling model exposed to delegate tools. ALE convention:
    no auto-magic sibling lookup; caller opts in explicitly."""

    # ---- loop control ----
    max_history_turns: int | None = None
    """Truncate replay-message history when restoring a transcript. None = unlimited."""

    disable_main_computer: bool = False
    """If True, the main agent has no ``computer`` tool — all GUI work goes
    through ``delegate_gui``. Mutually exclusive with :attr:`disable_delegate_gui`."""

    disable_delegate_gui: bool = False
    """If True, no GUI subagent — main agent uses its own ``computer``."""

    disabled_tools: list[str] = field(default_factory=lambda: ["web_search"])
    """Tools to drop from the assembled tool list (matched by ``BaseTool.name``).
    Defaults to ``["web_search"]`` because BRAVE_API_KEY is rarely provisioned;
    set to ``[]`` to opt back in (and provide :attr:`brave_api_key`)."""

    # ---- thinking levels (off | low | medium | high) ----
    thinking_level: str | None = None
    """Base thinking level. None → resolved-default for the model
    (see ``harness.thinking.resolve_thinking_default``)."""

    flush_thinking_level: str | None = None
    """Memory flush thinking. None → inherit :attr:`thinking_level`."""

    compaction_thinking_level: str | None = None
    """Compaction-rebuild thinking. None → inherit :attr:`thinking_level`."""

    vision_thinking_level: str = "off"
    """Vision/screenshot summarization thinking. Default off (cost)."""

    gui_thinking_level: str = "off"
    """``delegate_gui`` subagent thinking. Default off."""

    # ---- image retention ----
    image_retention_mode: str = "openclaw"
    """``openclaw`` (default — last N completed turns) or ``cua`` (last N images
    by count). OpenClaw mode reduces cache thrash on multi-screenshot turns."""

    # ---- documentation ----
    upstream_version: str = "openclaw-cua@a830cae2"
    """Source upstream commit for the vendored ``harness/`` tree.
    Surfaced via :attr:`AleClawDeployer.version`."""

    # ---- v2 (NOT in v1 — always per-run) ----
    # memory_base_dir: str | None = None
    # session_base_dir: str | None = None

    @property
    def is_openrouter(self) -> bool:
        return bool(self.openrouter_api_key) and self.model.startswith("openrouter/")

    def __post_init__(self) -> None:
        if not any([self.openrouter_api_key, self.anthropic_api_key, self.openai_api_key]):
            raise ValueError(
                "AleClawConfig requires at least one of "
                "openrouter_api_key / anthropic_api_key / openai_api_key"
            )
        if self.disable_main_computer and self.disable_delegate_gui:
            raise ValueError(
                "Both disable_main_computer and disable_delegate_gui set — "
                "agent has no way to interact with the VM."
            )
        for level_field, value in [
            ("thinking_level", self.thinking_level),
            ("flush_thinking_level", self.flush_thinking_level),
            ("compaction_thinking_level", self.compaction_thinking_level),
            ("vision_thinking_level", self.vision_thinking_level),
            ("gui_thinking_level", self.gui_thinking_level),
        ]:
            if value is not None and value not in ("off", "low", "medium", "high"):
                raise ValueError(
                    f"AleClawConfig.{level_field}={value!r} not in "
                    f"{{off, low, medium, high}}"
                )
