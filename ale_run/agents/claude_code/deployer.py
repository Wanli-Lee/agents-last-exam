"""ClaudeCodeDeployer — drives the @anthropic-ai/claude-code CLI.

Inherits :class:`BaseAgentDeployer` directly. All substrate I/O goes
through ``self.executor`` (vm / local / docker — see
:mod:`ale_run.executors`); this file holds **only** what's claude-code
specific:

* Verify the binary is present at the image-baked path.
* Write the MCP server config the CLI reads via ``--mcp-config``.
* Compose the OpenRouter env-var remap + the CLI argv per OS.
* Wrap stdin / stdout / stderr / done-marker around the CLI run.
* Parse the stream-json transcript into ATIF Steps.

The spawn-detached + done-marker poll + TERM+KILL mechanics live on
:class:`BaseExecutor`; the deployer just calls
``executor.spawn_detached`` / ``executor.wait_marker`` /
``executor.kill_process``.
"""
from __future__ import annotations

import json
import logging
import shlex
import time
from pathlib import Path
from typing import ClassVar

from ale_run.base_interface import (
    AgentRunResult,
    BaseAgentConfig,
    BaseAgentDeployer,
    ContentPart,
    Observation,
    StepMetrics,
    ToolCall,
    ToolResult,
    TrajectoryBuilder,
)

from .config import ClaudeCodeConfig

logger = logging.getLogger(__name__)


class ClaudeCodeDeployer(BaseAgentDeployer):
    """Host-side deployer for the @anthropic-ai/claude-code CLI."""

    default_executor: ClassVar[str] = "sandbox"
    supported_executors: ClassVar[frozenset[str]] = frozenset({"sandbox"})
    hot_artifacts: ClassVar[tuple[str, ...]] = ("transcript.jsonl", "stderr.log")

    @property
    def version(self) -> str | None:
        cfg: ClaudeCodeConfig = self.config  # type: ignore[assignment]
        return cfg.cli_version

    # =========================================================================
    # install — probe the binary, write MCP config, make work_dir
    # =========================================================================

    async def install(self) -> None:
        executor = self.executor
        sandbox = executor.sandbox

        # 1. Discover the claude binary on the sandbox. We don't bake the
        # path into the framework — different images can keep claude
        # wherever, as long as it's on PATH.
        claude_cmd = await self._discover_claude(sandbox)
        self._claude_cmd_cache = claude_cmd

        # 2. Verify it runs.
        if sandbox.is_linux:
            probe_cmd = f"{shlex.quote(claude_cmd)} --version"
        else:
            probe_cmd = (
                'powershell -NoProfile -Command "'
                f"& '{claude_cmd}' --version"
                '"'
            )
        result = await executor.run_command(probe_cmd, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(
                f"ClaudeCodeDeployer: claude CLI at {claude_cmd!r} failed "
                f"version probe: stderr={(result.stderr or '').strip()[:300]}"
            )
        logger.info(
            "claude_code: claude CLI ok — %s", (result.stdout or "").strip(),
        )

        # 3. Make work_dir.
        await executor.mkdir(executor.work_dir)

        # 4. Write MCP config using the sandbox's baked node + mcp paths.
        mcp_config = {
            "mcpServers": {
                "cua": {
                    "command": sandbox.node,
                    "args": [f"{sandbox.mcp_server_dir}/src/index.js"],
                },
            },
        }
        mcp_path = self._join(executor.work_dir, "mcp_config.json")
        await executor.write_file(mcp_path, json.dumps(mcp_config, indent=2))
        logger.info("claude_code: mcp_config staged at %s", mcp_path)

    async def _discover_claude(self, sandbox) -> str:
        """Resolve the claude binary's absolute path on the sandbox.

        Linux:   ``command -v claude``.
        Windows: ``(Get-Command claude).Source``.
        """
        if sandbox.is_linux:
            cmd = "command -v claude"
        else:
            cmd = (
                'powershell -NoProfile -Command "'
                "(Get-Command claude -ErrorAction Stop).Source"
                '"'
            )
        result = await self.executor.run_command(cmd, timeout=15)
        path = (result.stdout or "").strip()
        if result.returncode != 0 or not path:
            raise RuntimeError(
                f"ClaudeCodeDeployer: 'claude' not found on sandbox PATH. "
                f"Bake it into the image or install at provisioning time. "
                f"stderr={(result.stderr or '').strip()[:200]}"
            )
        return path

    # =========================================================================
    # launch — stage prompt, spawn detached, poll done.marker
    # =========================================================================

    async def launch(self, prompt: str) -> AgentRunResult:
        executor = self.executor
        cfg: ClaudeCodeConfig = self.config  # type: ignore[assignment]
        wd = executor.work_dir
        claude_cmd = getattr(self, "_claude_cmd_cache", None) or "claude"

        prompt_file = self._join(wd, "prompt.txt")
        transcript_file = self._join(wd, "transcript.jsonl")
        stderr_log = self._join(wd, "stderr.log")
        pid_file = self._join(wd, "claude.pid")
        done_marker = self._join(wd, "done.marker")
        mcp_config = self._join(wd, "mcp_config.json")

        await executor.write_file(prompt_file, prompt)

        if executor.sandbox.is_linux:
            script_body = self._linux_runner(
                cfg=cfg, wd=wd, claude_cmd=claude_cmd,
                prompt_file=prompt_file, transcript_file=transcript_file,
                stderr_log=stderr_log, done_marker=done_marker,
                mcp_config=mcp_config,
            )
            script_path = self._join(wd, "run_claude.sh")
        else:
            script_body = self._windows_runner(
                cfg=cfg, wd=wd, claude_cmd=claude_cmd,
                prompt_file=prompt_file, transcript_file=transcript_file,
                stderr_log=stderr_log, done_marker=done_marker,
                mcp_config=mcp_config,
            )
            script_path = self._join(wd, "run_claude.ps1")

        t0 = time.monotonic()
        pid = await executor.spawn_detached(
            script_body=script_body,
            script_path=script_path,
            pid_file=pid_file,
            reset_files=[done_marker, pid_file, stderr_log, transcript_file],
        )
        status, exit_code = await executor.wait_marker(
            done_marker, pid=pid, timeout=cfg.timeout_s,
        )
        duration_s = time.monotonic() - t0

        if status == "timeout":
            await executor.kill_process(pid)
            return AgentRunResult(
                status="timeout",
                pid=pid,
                transcript_path=transcript_file,
                stderr_path=stderr_log,
                duration_s=duration_s,
                error=f"wall budget {cfg.timeout_s}s exceeded",
            )

        if status == "crashed":
            return AgentRunResult(
                status="failed",
                pid=pid,
                transcript_path=transcript_file,
                stderr_path=stderr_log,
                duration_s=duration_s,
                error="process disappeared before writing done.marker; see stderr",
            )

        error: str | None = None
        if status == "failed":
            error = await self._diagnose_failure(
                stderr_log=stderr_log,
                transcript=transcript_file,
                exit_code=exit_code,
            )
        return AgentRunResult(
            status=status,
            pid=pid,
            exit_code=exit_code,
            transcript_path=transcript_file,
            stderr_path=stderr_log,
            duration_s=duration_s,
            error=error,
        )

    # =========================================================================
    # OS-aware path join (substrate convention, not host's os.path)
    # =========================================================================

    def _join(self, *parts: str) -> str:
        sep = "/" if self.executor.sandbox.is_linux else "\\"
        head = parts[0].rstrip("/\\")
        tail = sep.join(p.strip("/\\") for p in parts[1:])
        return f"{head}{sep}{tail}" if tail else head

    # =========================================================================
    # per-OS runner bodies
    # =========================================================================

    @staticmethod
    def _build_argv_linux(
        *, claude_cmd: str, cfg: ClaudeCodeConfig, mcp_config: str,
    ) -> str:
        argv = [
            shlex.quote(claude_cmd), "-p", "-",
            "--output-format", "stream-json", "--verbose",
            "--mcp-config", shlex.quote(mcp_config),
            "--model", shlex.quote(cfg.model),
        ]
        if cfg.max_turns is not None and cfg.max_turns >= 0:
            argv += ["--max-turns", str(cfg.max_turns)]
        if cfg.max_budget_usd is not None:
            argv += ["--max-budget-usd", str(cfg.max_budget_usd)]
        if cfg.dangerously_skip_permissions:
            argv += ["--dangerously-skip-permissions"]
        for tool in cfg.disabled_tools:
            argv += ["--disallowedTools", shlex.quote(tool)]
        return " ".join(argv)

    def _linux_runner(
        self, *, cfg, wd, claude_cmd, prompt_file, transcript_file,
        stderr_log, done_marker, mcp_config,
    ) -> str:
        env = dict(self.executor.env)
        base_url_default = cfg.base_url or "https://openrouter.ai/api"
        env_lines: list[str] = []
        if not env.get("ANTHROPIC_API_KEY") and env.get("OPENROUTER_API_KEY"):
            env_lines += [
                f"export ANTHROPIC_BASE_URL={shlex.quote(base_url_default)}",
                f'export ANTHROPIC_AUTH_TOKEN={shlex.quote(env["OPENROUTER_API_KEY"])}',
                'export ANTHROPIC_API_KEY=""',
            ]
        elif env.get("ANTHROPIC_API_KEY"):
            env_lines.append(
                f'export ANTHROPIC_API_KEY={shlex.quote(env["ANTHROPIC_API_KEY"])}'
            )
        if cfg.base_url:
            env_lines.append(f"export ANTHROPIC_BASE_URL={shlex.quote(cfg.base_url)}")

        cmd_line = self._build_argv_linux(
            claude_cmd=claude_cmd, cfg=cfg, mcp_config=mcp_config,
        )
        return (
            "#!/bin/bash\nset -u\n"
            + "\n".join(env_lines) + ("\n" if env_lines else "")
            + f"cd {shlex.quote(wd)}\n"
            + f"prompt=$(cat {shlex.quote(prompt_file)})\n"
            + f"echo \"$prompt\" | {cmd_line} "
            + f"2>{shlex.quote(stderr_log)} >{shlex.quote(transcript_file)}\n"
            + f"echo $? > {shlex.quote(done_marker)}\n"
        )

    @staticmethod
    def _build_argv_windows(
        *, claude_cmd: str, cfg: ClaudeCodeConfig, mcp_config: str,
    ) -> str:
        argv = [
            f"& '{claude_cmd}'", "-p", "-",
            "--output-format", "stream-json", "--verbose",
            "--mcp-config", f"'{mcp_config}'",
            "--model", cfg.model,
        ]
        if cfg.max_turns is not None and cfg.max_turns >= 0:
            argv += ["--max-turns", str(cfg.max_turns)]
        if cfg.max_budget_usd is not None:
            argv += ["--max-budget-usd", str(cfg.max_budget_usd)]
        if cfg.dangerously_skip_permissions:
            argv += ["--dangerously-skip-permissions"]
        for tool in cfg.disabled_tools:
            argv += ["--disallowedTools", f"'{tool}'"]
        return " ".join(argv)

    def _windows_runner(
        self, *, cfg, wd, claude_cmd, prompt_file, transcript_file,
        stderr_log, done_marker, mcp_config,
    ) -> str:
        env = dict(self.executor.env)
        base_url_default = cfg.base_url or "https://openrouter.ai/api"
        env_lines: list[str] = []
        if not env.get("ANTHROPIC_API_KEY") and env.get("OPENROUTER_API_KEY"):
            env_lines += [
                f"$env:ANTHROPIC_BASE_URL = '{base_url_default}'",
                f"$env:ANTHROPIC_AUTH_TOKEN = '{env['OPENROUTER_API_KEY']}'",
                "$env:ANTHROPIC_API_KEY = ''",
            ]
        elif env.get("ANTHROPIC_API_KEY"):
            env_lines.append(
                f"$env:ANTHROPIC_API_KEY = '{env['ANTHROPIC_API_KEY']}'"
            )
        if cfg.base_url:
            env_lines.append(f"$env:ANTHROPIC_BASE_URL = '{cfg.base_url}'")

        cmd_line = self._build_argv_windows(
            claude_cmd=claude_cmd, cfg=cfg, mcp_config=mcp_config,
        )
        return (
            "$ErrorActionPreference = 'Continue'\n"
            "$utf8 = New-Object System.Text.UTF8Encoding($false)\n"
            "[Console]::InputEncoding = $utf8\n"
            "[Console]::OutputEncoding = $utf8\n"
            "$OutputEncoding = $utf8\n"
            + "\n".join(env_lines) + ("\n" if env_lines else "")
            + f"Set-Location -LiteralPath '{wd}'\n"
            + f"$prompt = Get-Content -LiteralPath '{prompt_file}' -Encoding UTF8 -Raw\n"
            + f"$prompt | {cmd_line} 2>'{stderr_log}' | Out-File -FilePath '{transcript_file}' -Encoding utf8\n"
            + f"$LASTEXITCODE | Out-File -FilePath '{done_marker}' -Encoding ascii -NoNewline\n"
        )

    # =========================================================================
    # failure diagnosis
    # =========================================================================

    async def _diagnose_failure(
        self, *, stderr_log: str, transcript: str, exit_code: int | None,
    ) -> str:
        parts = [f"agent failed (rc={exit_code})"]
        stderr_text = await self.executor.read_text(stderr_log)
        tx_text = await self.executor.read_text(transcript)
        parts.append(f"stderr={len(stderr_text)}B transcript={len(tx_text)}B")
        if stderr_text.strip():
            parts.append(f"stderr tail: ...{stderr_text[-800:]}")
        if '"authentication_failed"' in tx_text or '"User not found"' in tx_text:
            parts.append("LLM auth failed (check api keys)")
        elif '"error_status":429' in tx_text or '"rate_limit_error"' in tx_text:
            parts.append("LLM rate-limited")
        elif '"error_status":5' in tx_text:
            parts.append("LLM upstream 5xx")
        elif '"type":"result"' not in tx_text and exit_code != 0:
            parts.append("agent never produced result event")
        if tx_text.strip():
            parts.append(f"transcript tail: ...{tx_text[-800:]}")
        return " | ".join(parts)

    # =========================================================================
    # parse_artifacts — host-side, reads gathered transcript.jsonl
    # =========================================================================

    @classmethod
    def parse_artifacts(
        cls,
        *,
        work_dir: Path,
        config: BaseAgentConfig,
        run_result: AgentRunResult,
        builder: TrajectoryBuilder,
    ) -> None:
        transcript_file = work_dir / "transcript.jsonl"
        if not transcript_file.exists():
            builder.add_step(
                source="system",
                message=f"claude-code: no transcript at {transcript_file}",
                extra={"reason": "no_transcript"},
            )
            return

        raw = transcript_file.read_text()
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            cls._consume_event(event, builder)

        builder.trajectory.extra.setdefault("claude_code", {}).update({
            "exit_code": run_result.exit_code,
            "transcript_path": str(transcript_file),
            "stderr_path": run_result.stderr_path,
        })

    @classmethod
    def _consume_event(cls, event: dict, builder: TrajectoryBuilder) -> None:
        etype = event.get("type")
        if etype == "assistant":
            cls._consume_assistant(event, builder)
        elif etype == "user":
            cls._consume_user(event, builder)
        elif etype == "system":
            builder.trajectory.extra.setdefault("system_events", []).append(event)
        elif etype == "result":
            builder.trajectory.extra["result"] = event

    @staticmethod
    def _consume_assistant(event: dict, builder: TrajectoryBuilder) -> None:
        message = event.get("message", {}) or {}
        content_blocks = message.get("content", []) or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in content_blocks:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id") or "",
                    name=block.get("name") or "",
                    arguments=block.get("input") or {},
                ))
        usage = message.get("usage") or {}
        metrics = StepMetrics(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            cache_creation_tokens=usage.get("cache_creation_input_tokens"),
        )
        builder.add_step(
            source="agent",
            message="\n".join(p for p in text_parts if p) or None,
            tool_calls=tool_calls,
            metrics=metrics,
            extra={"stop_reason": message.get("stop_reason")},
        )

    @staticmethod
    def _consume_user(event: dict, builder: TrajectoryBuilder) -> None:
        message = event.get("message", {}) or {}
        content_blocks = message.get("content", []) or []
        results: list[ToolResult] = []
        text_parts: list[str] = []
        for block in content_blocks:
            btype = block.get("type")
            if btype == "tool_result":
                content = block.get("content")
                parts: list[ContentPart] = []
                if isinstance(content, str):
                    parts.append(ContentPart(type="text", text=content))
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            parts.append(ContentPart(type="text", text=c.get("text", "")))
                results.append(ToolResult(
                    tool_call_id=block.get("tool_use_id") or "",
                    content=parts,
                    is_error=bool(block.get("is_error")),
                ))
            elif btype == "text":
                text_parts.append(block.get("text", ""))
        builder.add_step(
            source="environment",
            message="\n".join(p for p in text_parts if p) or None,
            observation=Observation(results=results),
        )
