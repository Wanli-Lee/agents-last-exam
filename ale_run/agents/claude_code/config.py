"""ClaudeCodeConfig: per-episode knobs for the Claude Code CLI deployer.

**API keys live in the operator's shell env**, never in this config.
The deployer's VM-side bash script reads ``ANTHROPIC_API_KEY`` /
``OPENROUTER_API_KEY`` from the inherited env (propagated host → VM by
:mod:`ale.runtime._env`). OpenRouter routing auto-detects: if
``ANTHROPIC_API_KEY`` is unset but ``OPENROUTER_API_KEY`` is set, the
script remaps to ``ANTHROPIC_AUTH_TOKEN`` + ``ANTHROPIC_BASE_URL``.

Typical usage::

    # In shell:
    #   export ANTHROPIC_API_KEY=sk-ant-...    # direct
    #   # OR
    #   export OPENROUTER_API_KEY=sk-or-...    # routed (auto-detected)

    cfg = ClaudeCodeConfig(
        model="claude-opus-4-7",
        max_budget_usd=5.0,
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

# Built-in Claude Code tools that break headless (`-p`) runs. Mirrors the
# default disabled_tools list shipped in agenthle's claude_code_openrouter.yaml
# — passed to the CLI as repeated ``--disallowedTools`` flags. Each either
# blocks on human interaction or mutates persistent session state with no
# headless equivalent, so leaving them enabled risks deadlocks.
_DISABLED_TOOLS = (
    # Plan mode needs interactive user approval (ExitPlanMode waits for a
    # human accept) — deadlocks headless runs.
    "EnterPlanMode",
    "ExitPlanMode",
    # Worktree tools mutate session CWD with persistent side effects.
    "EnterWorktree",
    "ExitWorktree",
    # Pure user-interaction tool — no headless equivalent.
    "AskUserQuestion",
    # Background task lifecycle (no running task ID exists in headless).
    "TaskOutput",
    "TaskStop",
    # Requires a logged-in claude.ai account; benchmark VMs are not.
    "RemoteTrigger",
)


@dataclass
class ClaudeCodeConfig:
    """Tunables for :class:`ClaudeCodeDeployer`.

    Standalone config (no shared base). The episode wall-budget is
    orchestration-owned; ``timeout_s`` is no longer an agent knob.
    """

    name: ClassVar[str] = "claude-code"

    # agenthle claude_code_openrouter.yaml: anthropic/claude-opus-4.6
    # (direct claude_code.yaml: claude-sonnet-4-6).
    model: str = "anthropic/claude-opus-4.6"

    # agenthle claude_code_openrouter.yaml: max_turns: -1 (≡ unlimited; the
    # deployer omits --max-turns when < 0). Direct claude_code.yaml: 300.
    # The base class used to leave this None → --max-turns was always
    # skipped; pinning -1 restores the explicit-unlimited intent.
    max_turns: int | None = -1

    # ---- routing (no secrets — API keys come from shell env) ----
    provider: str = "openrouter"
    """Routing provider, drives env setup explicitly (not key-presence
    heuristics):
      - ``"openrouter"`` → ANTHROPIC_BASE_URL=openrouter, AUTH_TOKEN=
        OPENROUTER_API_KEY, ANTHROPIC_API_KEY="". Requires OPENROUTER_API_KEY.
      - ``"direct"`` → uses ANTHROPIC_API_KEY against anthropic.com (or
        ``base_url`` if set). Requires ANTHROPIC_API_KEY.
    Missing the required key for the chosen provider is a hard error."""

    base_url: str | None = None
    """Custom Anthropic-compatible base URL. Overrides the provider's
    default ``ANTHROPIC_BASE_URL``."""

    # ---- CLI knobs ----
    max_budget_usd: float | None = None
    disabled_tools: tuple[str, ...] = _DISABLED_TOOLS
    dangerously_skip_permissions: bool = True

    max_thinking_tokens: int = 31999
    """Extended-thinking token budget, passed to the CLI via the
    ``MAX_THINKING_TOKENS`` env var (Claude Code's documented knob —
    see https://code.claude.com/docs/en/costs#adjust-extended-thinking).
    Claude Code enables extended thinking by default; ``31999`` is the
    default-high ("ultrathink") cap. We set it explicitly so the reasoning
    level is pinned + visible rather than relying on the CLI default
    (parity with codex's ``reasoning_effort=high``). Lower it (e.g. 8000)
    to cut cost, or set 0 to disable thinking."""

    # ---- documentation ----
    cli_version: str = "@anthropic-ai/claude-code@2.1.85"
    """Full npm spec the deployer installs when ``claude`` is not already on
    PATH (e.g. on a non-prebaked image). When the binary is baked into the
    image this is just the version of record."""
