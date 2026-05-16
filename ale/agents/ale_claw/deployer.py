"""AleClawDeployer — first native (host-side, in-process) deployer in ALE.

The OpenClaw harness lives in :mod:`ale.agents.ale_claw.harness` (copied
from ``cua_bench/agents/openclaw/`` upstream, see
:attr:`AleClawConfig.upstream_version`). It runs **in this Python
process**: the LLM loop, tool dispatch, memory + session persistence
all happen on the ALE host. The agent reaches the test VM via
``env.session.computer`` (the cua Computer SDK), exactly like the
agenthle native runner did.

What this file replaces:

- agenthle's ``orchestration/agents/ale_claw/agent.py`` (8 hook overrides
  on a thin subclass).
- upstream's ``cua_bench/agents/openclaw_agent.py::OpenClawAgent.perform_task``
  body (the ~340-line orchestration: build memory_store / session_mgr /
  tools / OpenClawComputerAgent, then drive the async-generator loop).

Both fold into :meth:`AleClawDeployer.launch` as procedural code. There
is no inheritance from upstream's ``OpenClawAgent`` and no monkey-
patching — the harness is just a library we call.

Lifecycle map:
  ``BaseAgentDeployer.install`` → sanity-check imports + at least one API key
  ``BaseAgentDeployer.launch``  → set up work_dir, build OpenClaw, drive run
  ``BaseAgentDeployer.collect`` → parse on-disk transcripts → ALE Steps
  ``BaseAgentDeployer.work_dir`` → return host tempdir (work_dir_on_vm=False)

Concurrency caveat: API keys are injected via ``os.environ`` for litellm to
read. Multiple concurrent units with DIFFERENT keys race on the env; v1
assumes same key across all units. v2 fix is subprocess isolation.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from ale.agents.base import AgentRunResult, BaseAgentDeployer
from ale.agents.trajectory import TrajectoryBuilder

from .config import AleClawConfig
from .transcript_to_trajectory import parse_transcripts_into

# Harness imports (all from our in-tree harness/ — no cua_bench.agents.openclaw).
from .harness import (
    OpenClawComputerAgent,
    OpenClawComputerHandler,
    SessionManager,
    MemoryStore,
    SubagentRegistry,
    build_tools,
    get_tool_summaries,
    ToolLoggingCallback,
    ContextOverflowCallback,
    build_system_prompt_report,
    PromptBuilder,
    ContextFile,
    ThinkingConfig,
    ThinkLevel,
    resolve_thinking_default,
    build_replay_messages,
    sanitize_history,
    limit_history_turns,
    convert_to_responses_api_items,
)
from .harness.agent_loop import has_done_signal
from .harness.context import DEFAULT_CONTEXT_TOKENS, resolve_context_window
from .harness.model_config import resolve_model

if TYPE_CHECKING:
    import cua_bench as cb

logger = logging.getLogger(__name__)


# Path to the harness's system-prompt context file (ships next to harness/).
# Read at every launch — kept on disk (not as a Python string) so the openclaw
# repo's bootstrap convention is preserved verbatim.
_HARNESS_AGENTS_MD = Path(__file__).resolve().parent / "harness" / "AGENTS.md"


class AleClawDeployer(BaseAgentDeployer):
    """Native, host-side, in-process OpenClaw deployer."""

    work_dir_on_vm: ClassVar[bool] = False

    def __init__(self, config: AleClawConfig):
        self._cfg = config
        # Per-launch state — set in :meth:`launch`, read by :meth:`work_dir`
        # and :meth:`collect`.
        self._work_dir: Path | None = None
        # Harness-internal id for memory + session keying. Set per launch from
        # a uuid; meaningless to ALE but the harness wants something stable
        # within a run (it becomes a folder name under work_dir). ALE-side
        # task identity stays out of here — the run_dir path already carries
        # the human-readable task slug via the runner's output layout.
        self._task_id: str = "default"

    # ---- BaseAgentDeployer required surface ---------------------------------

    @property
    def config(self) -> AleClawConfig:
        return self._cfg

    @property
    def version(self) -> str | None:
        return self._cfg.upstream_version

    async def install(self, session: "cb.DesktopSession") -> None:
        """Sanity check: imports resolve + at least one API key is present.

        Native deployer — nothing to install on the VM. The harness already
        lives in-process. We use ``session`` only to validate it's alive
        before launch (a no-op call costs ~one RPC round-trip).
        """
        # Touch the harness to validate the in-process import chain (no-op
        # in steady state but catches refactor breakage early).
        from .harness.agent_loop import OpenClawComputerAgent  # noqa: F401
        if not any([
            self._cfg.openrouter_api_key,
            self._cfg.anthropic_api_key,
            self._cfg.openai_api_key,
        ]):
            raise RuntimeError(
                "AleClawConfig has no API key set "
                "(openrouter_api_key / anthropic_api_key / openai_api_key)"
            )
        logger.info("ale-claw: install ok (model=%s)", self._cfg.model)

    async def launch(
        self,
        session: "cb.DesktopSession",
        *,
        prompt: str,
        timeout_s: float,
    ) -> AgentRunResult:
        """Drive the OpenClaw agent end-to-end against ``session``.

        Body adapted from upstream's ``OpenClawAgent.perform_task``. Same
        moving parts (memory_store, session_mgr, registry, model resolve,
        tools, prompt, overflow_cb, OpenClawComputerAgent ctor, async
        generator drive) but flattened into procedural code with our
        config + work_dir.
        """
        # ---- 1. Per-run work_dir on host ------------------------------------
        run_id = uuid.uuid4().hex[:12]
        # task_id is harness-internal; we use the run_id directly so a single
        # `ls openclaw_sessions/` lines up with the run_id surfaced elsewhere
        # in logs. The run_dir's outer path (carries the task slug via the
        # runner output layout) is where ALE identifies which task this is.
        self._task_id = run_id
        self._work_dir = Path(tempfile.gettempdir()) / "ale" / "ale_claw" / run_id
        self._work_dir.mkdir(parents=True, exist_ok=True)
        memory_base = self._work_dir / "openclaw_memory"
        session_base = self._work_dir / "openclaw_sessions"
        trajectory_dir = self._work_dir / "trajectories"
        trajectory_dir.mkdir(parents=True, exist_ok=True)
        logger.info("ale-claw: work_dir=%s", self._work_dir)

        # ---- 2. Memory + session + subagent registry ------------------------
        memory_store = MemoryStore(task_id=self._task_id, base_dir=str(memory_base))
        memory_store.init_session()
        session_mgr = SessionManager(task_id=self._task_id, base_dir=str(session_base))
        session_mgr.init_session(model=self._cfg.model)

        registry = SubagentRegistry(
            persist_path=session_mgr.task_dir / "subagent-runs.jsonl",
        )
        registry.restore()

        # ---- 3. Model resolution + context window ---------------------------
        resolved_model = resolve_model(self._cfg.model)
        summary_model = self._resolve_summary_model()
        resolved_summary_model = (
            resolved_model if summary_model == self._cfg.model
            else resolve_model(summary_model)
        )

        ctx_override = os.environ.get("CONTEXT_WINDOW_OVERRIDE")
        if ctx_override:
            context_window_tokens = int(ctx_override)
        else:
            context_window_tokens = (
                resolved_model.context_window
                or resolve_context_window(self._cfg.model)
                or DEFAULT_CONTEXT_TOKENS
            )

        # workspace_root=None → permissive (no FS-tool path bound). User
        # confirmed: "no limitations, full access to VMs". Downstream
        # docstrings on read/write/exec tools document the contract.
        workspace_root: str | None = None
        host_workspace_root = str(memory_store.task_dir.resolve())

        # ---- 4. Thinking config (per-call-site levels) ----------------------
        thinking_config = self._build_thinking_config()
        thinking_api_params = thinking_config.to_api_params(self._cfg.model)
        gui_thinking_params = thinking_config.gui_params(
            self._cfg.gui_model or self._cfg.model,
        )

        # ---- 5. Pre-build computer handler (replaces _make_computer_handler hook) -
        # Pre-init to satisfy build_tools' ``isinstance(_, AsyncComputerHandler)``
        # short-circuit; otherwise it would auto-instantiate a vanilla
        # cuaComputerHandler (without our keypress/coord fixes).
        computer_handler = None
        if not self._cfg.disable_main_computer:
            computer_handler = OpenClawComputerHandler(session.computer)
            await computer_handler._initialize()                # noqa: SLF001

        # ---- 6. Tool assembly + disabled_tools filter -----------------------
        tools = build_tools(
            session, memory_store,
            summary_model=summary_model,
            vision_thinking_params=thinking_config.vision_params(
                summary_model, runtime=resolved_summary_model,
            ),
            registry=registry,
            parent_session_dir=session_mgr.task_dir,
            default_model=self._cfg.model,
            lightweight_model=self._cfg.lightweight_model,
            thinking_params=thinking_api_params,
            gui_thinking_params=gui_thinking_params,
            disable_main_computer=self._cfg.disable_main_computer,
            disable_delegate_gui=self._cfg.disable_delegate_gui,
            gui_model=self._cfg.gui_model,
            workspace_root=workspace_root,
            host_workspace_root=host_workspace_root,
            context_window_tokens=context_window_tokens,
            computer_handler=computer_handler,
        )
        if self._cfg.disabled_tools:
            tools = [t for t in tools if getattr(t, "name", "") not in self._cfg.disabled_tools]
            logger.info("ale-claw: disabled_tools=%s", self._cfg.disabled_tools)
        tool_summaries = get_tool_summaries(tools)

        # ---- 7. System prompt — AGENTS.md + TASK_MEMORY.md context files ----
        agents_md = _HARNESS_AGENTS_MD.read_text(encoding="utf-8")
        context_files = [ContextFile(path="AGENTS.md", content=agents_md)]
        bootstrap = memory_store.get_bootstrap_context()
        if bootstrap:
            context_files.append(ContextFile(path="TASK_MEMORY.md", content=bootstrap))

        instructions = PromptBuilder().build(
            tool_summaries=tool_summaries, context_files=context_files,
        )
        report = build_system_prompt_report(
            system_prompt=instructions, context_files=context_files,
            tool_summaries=tool_summaries, tools=tools,
        )
        session_mgr.set_system_prompt_report(report)

        # ---- 8. Overflow callback + agent ----------------------------------
        overflow_cb = ContextOverflowCallback(
            model=self._cfg.model,
            context_window=context_window_tokens,
            instructions_tokens=len(instructions) // 4,
            resolved_model=resolved_model,
        )
        if session_mgr._state is not None:                       # noqa: SLF001
            session_mgr._state.contextTokens = overflow_cb.context_window  # noqa: SLF001
            session_mgr.save_state()

        agent = OpenClawComputerAgent(
            # ComputerAgent params
            model=self._cfg.model,
            tools=tools,
            only_n_most_recent_images=3,
            trajectory_dir=trajectory_dir,
            instructions=instructions,
            use_prompt_caching=True,
            callbacks=[ToolLoggingCallback()],
            context_files=context_files,
            image_retention_mode=self._cfg.image_retention_mode,
            auto_screenshot=False,
            # OpenClaw compaction params
            overflow_cb=overflow_cb,
            session_mgr=session_mgr,
            memory_store=memory_store,
            summary_model=summary_model,
            # Thinking config
            thinking_config=thinking_config,
            resolved_model=resolved_model,
            summary_runtime=resolved_summary_model,
            # Subagent delegation
            registry=registry,
            # Provider-specific thinking kwargs → ComputerAgent additional_generation_kwargs
            **thinking_api_params,
        )

        # ---- 9. Cross-run replay (always empty in v1 — per-run mode) -------
        # NOTE: per-run for v1; cross-run resume would feed prior_entries here
        # and let openclaw replay the conversation. Future config flag.
        prior_entries = session_mgr.load_history()
        replay_messages: list[dict[str, Any]] = []
        if prior_entries:
            replay_messages = build_replay_messages(prior_entries)
            replay_messages = sanitize_history(replay_messages)
            replay_messages = limit_history_turns(
                replay_messages, self._cfg.max_history_turns,
            )
            replay_messages = sanitize_history(replay_messages)
            replay_messages = convert_to_responses_api_items(replay_messages)
        run_input = (
            replay_messages + [{"role": "user", "content": prompt}]
            if replay_messages else prompt
        )

        # ---- 10. Drive the loop with timeout + env-patched API keys --------
        env_patches = self._prepare_env()
        max_steps = self._cfg.max_turns or 100
        total_usage = {
            "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "response_cost": 0.0,
        }
        t0 = time.monotonic()
        step = 0
        task_completed = False

        with self._patched_environ(env_patches):
            try:
                async def _drive() -> None:
                    nonlocal step, task_completed
                    async for result in agent.run(run_input):
                        sys.stdout.flush()
                        step += 1
                        for k in total_usage:
                            total_usage[k] += result["usage"].get(k, 0)
                        session_mgr.update_step_count(step)
                        session_mgr.update_tokens(
                            result["usage"].get("input_tokens", 0),
                            result["usage"].get("output_tokens", 0),
                        )
                        if step >= max_steps:
                            logger.info("ale-claw: max_steps %d reached", max_steps)
                            break
                        if has_done_signal(result.get("output", [])):
                            logger.info("ale-claw: done signal at step %d", step)
                            task_completed = True
                            break
                await asyncio.wait_for(_drive(), timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.warning("ale-claw: wall budget %.0fs exceeded", timeout_s)
                return AgentRunResult(
                    status="timeout",
                    duration_s=time.monotonic() - t0,
                    error=f"wall budget {timeout_s}s exceeded",
                    transcript_path=str(self._first_transcript() or ""),
                )
            except Exception as exc:                            # noqa: BLE001
                logger.exception("ale-claw: agent.run threw")
                return AgentRunResult(
                    status="failed",
                    duration_s=time.monotonic() - t0,
                    error=f"{type(exc).__name__}: {exc}",
                    transcript_path=str(self._first_transcript() or ""),
                )

        # Outcome mapping (mirrors agenthle's _LOOP_EXIT_FAILURE_MODE=UNKNOWN
        # — loop exit without done & without max_steps is a real failure).
        if task_completed:
            status = "completed"
            error: str | None = None
        elif step >= max_steps:
            # Finished within step budget. Not a wall-clock timeout; map
            # to "completed" with extra annotation so eval treats it as
            # a real attempt.
            status = "completed"
            error = None
        else:
            status = "failed"
            error = "loop exited without done signal"

        return AgentRunResult(
            status=status,
            duration_s=time.monotonic() - t0,
            transcript_path=str(self._first_transcript() or ""),
            error=error,
        )

    async def collect(
        self,
        session: "cb.DesktopSession",
        run: AgentRunResult,
        builder: TrajectoryBuilder,
    ) -> None:
        """Parse on-disk transcripts → ATIF Steps via the translator module."""
        if not self._work_dir or not self._work_dir.exists():
            builder.add_step(
                source="system",
                message="ale-claw: no work_dir to parse",
                extra={"reason": "no_work_dir"},
            )
            return
        try:
            parse_transcripts_into(self._work_dir, builder)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("ale-claw: collect failed")
            builder.add_step(
                source="system",
                message=f"transcript parse failed: {type(exc).__name__}: {exc}",
                extra={"reason": "parse_error"},
            )
        # Surface where everything is for downstream debug.
        builder.trajectory.extra.setdefault("ale_claw", {}).update({
            "work_dir": str(self._work_dir),
            "version": self._cfg.upstream_version,
            "transcript_path": run.transcript_path,
            "task_id": self._task_id,
        })

    def work_dir(self, session: "cb.DesktopSession") -> str | None:
        """Return the host tempdir created in :meth:`launch`.

        Native deployer — work_dir_on_vm=False — so the framework's
        :meth:`mirror_artifacts` will ``shutil.copytree`` this into
        ``<run_dir>/origin_log/ale-claw/``.
        """
        return str(self._work_dir) if self._work_dir else None

    # ---- helpers (former agenthle hooks, now plain methods) -----------------

    def _resolve_summary_model(self) -> str:
        """Mirror of agenthle ``_default_summary_model``: lightweight or main."""
        return self._cfg.summary_model or self._cfg.lightweight_model or self._cfg.model

    def _build_thinking_config(self) -> ThinkingConfig:
        """Mirror of upstream OpenClawAgent's thinking-config wiring."""
        c = self._cfg
        level = (
            ThinkLevel(c.thinking_level) if c.thinking_level
            else resolve_thinking_default(c.model)
        )
        flush = ThinkLevel(c.flush_thinking_level) if c.flush_thinking_level else level
        compact = (
            ThinkLevel(c.compaction_thinking_level) if c.compaction_thinking_level
            else level
        )
        vision = ThinkLevel(c.vision_thinking_level)
        gui = ThinkLevel(c.gui_thinking_level)
        return ThinkingConfig(
            level=level, flush_level=flush, compaction_level=compact,
            vision_level=vision, gui_level=gui,
        )

    def _prepare_env(self) -> dict[str, str]:
        """Collect API keys this config carries into ``{ENV_NAME: value}``."""
        env: dict[str, str] = {}
        if self._cfg.openrouter_api_key:
            env["OPENROUTER_API_KEY"] = self._cfg.openrouter_api_key
        if self._cfg.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self._cfg.anthropic_api_key
        if self._cfg.openai_api_key:
            env["OPENAI_API_KEY"] = self._cfg.openai_api_key
        if self._cfg.brave_api_key:
            env["BRAVE_API_KEY"] = self._cfg.brave_api_key
        return env

    @contextlib.contextmanager
    def _patched_environ(self, env: dict[str, str]):
        """Temporarily set ``env`` into ``os.environ``, restoring on exit.

        Required because litellm + the anthropic SDK read keys from env vars.
        ALE convention: never read keys from env in config — config carries
        them, deployer injects just-in-time, then unwinds.
        """
        old: dict[str, str | None] = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            yield
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def _first_transcript(self) -> Path | None:
        """First ``transcript.jsonl`` written under our work_dir."""
        if not self._work_dir:
            return None
        ts = sorted((self._work_dir / "openclaw_sessions").glob("*/transcript.jsonl"))
        return ts[0] if ts else None
