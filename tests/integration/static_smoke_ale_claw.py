"""End-to-end smoke for AleClawDeployer × demo/hello against pre-existing dev VMs.

Uses :class:`StaticProvider` against pre-existing dev VMs (no gcloud
lifecycle, no boot wait). The agent process runs in this Python process
(native), drives the VM via env.session.computer.

Usage::

    OPENROUTER_API_KEY=... uv run python tests/integration/static_smoke_ale_claw.py linux
    OPENROUTER_API_KEY=... uv run python tests/integration/static_smoke_ale_claw.py windows

Required env:
    OPENROUTER_API_KEY  — provider creds (passed to AleClawConfig)
    OPENROUTER_MODEL    — default openrouter/anthropic/claude-sonnet-4-20250514

Cost: ~$0.05 / run (Sonnet 4 + ~10 turns). VM is pre-running (no infra cost).

Pre-flight (one-time per session):
    curl -X POST http://34.94.179.145:5000/cmd -H 'content-type: application/json' \\
      -d '{"command":"run_command","params":{"command":"echo ok"}}'
    curl -X POST http://34.57.85.163:5000/cmd  -H 'content-type: application/json' \\
      -d '{"command":"run_command","params":{"command":"echo ok"}}'
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ale
from ale.agents.ale_claw import AleClawConfig, AleClawDeployer
from ale.io import RunWriter, slug_task
from ale.io.artifact_mirror import ArtifactMirror, ArtifactMirrorConfig
from ale.providers.static import StaticProvider, StaticProviderConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("static_smoke_ale_claw")


PROFILES = {
    "linux":   {"endpoint": "http://34.94.179.145:5000", "os": "linux"},
    "windows": {"endpoint": "http://34.57.85.163:5000",  "os": "windows"},
}


def build_config() -> AleClawConfig:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise SystemExit("OPENROUTER_API_KEY required for smoke")
    model = os.environ.get(
        "OPENROUTER_MODEL", "openrouter/anthropic/claude-sonnet-4-20250514",
    )
    return AleClawConfig(
        model=model,
        openrouter_api_key=openrouter_key,
        max_turns=20,
        timeout_s=900.0,
        disabled_tools=["web_search"],
    )


def _install_signal_handlers() -> None:
    def _on_signal(signum, frame):
        raise KeyboardInterrupt(f"received signal {signum}")
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass


async def run_once(os_kind: str, variant_index: int = 0) -> int:
    _install_signal_handlers()
    if os_kind not in PROFILES:
        raise SystemExit(f"unknown os_kind: {os_kind!r} (linux|windows)")
    profile = PROFILES[os_kind]
    cfg = build_config()

    output_root = Path(f".logs/static_smoke_ale_claw_{os_kind}")
    rw = RunWriter.create(
        output_root=output_root,
        agent_name="ale-claw",
        model=cfg.model,
        task_path="demo/hello",
        variant_index=variant_index,
    )
    rw.emit_event(
        "run_started",
        agent="ale-claw",
        model=cfg.model,
        task="demo/hello",
        variant_index=variant_index,
        endpoint=profile["endpoint"],
        os=profile["os"],
    )

    provider = StaticProvider(StaticProviderConfig(
        endpoint=profile["endpoint"],
        os=profile["os"],
    ))
    env = ale.make("demo/hello", provider=provider)
    deployer = AleClawDeployer(cfg)

    t0 = time.monotonic()
    status = "not_executed"
    error: str | None = None
    reward = None
    trajectory = None
    eval_status = "not_executed"
    eval_duration_s: float | None = None
    eval_error = None
    mirror_report: dict = {}

    try:
        try:
            rw.emit_event("agent_run_started", endpoint=profile["endpoint"])
            result = await deployer.run(env, variant_index=variant_index)
            rw.emit_event(
                "agent_finished",
                status=result.status, reward=result.reward,
                eval_status=result.eval_status,
            )
            status = result.status
            error = result.error
            reward = result.reward
            trajectory = result.trajectory
            eval_status = result.eval_status
            eval_duration_s = result.eval_duration_s
            eval_error = result.eval_error

            mirror = ArtifactMirror(ArtifactMirrorConfig.from_env(
                local_root=rw.run_dir, run_id=rw.run_id,
            ))
            rw.emit_event("artifact_mirror_started",
                          gcs_bucket=mirror._cfg.gcs_bucket or "(local copytree)")
            mirror_report = await deployer.mirror_artifacts(env, mirror)
            rw.emit_event("artifact_mirror_done", report=mirror_report)
        except (KeyboardInterrupt, asyncio.CancelledError) as exc:
            status = "cancelled"
            error = f"{type(exc).__name__}: external signal / cancel"
            rw.emit_event("run_cancelled", reason=str(exc) or type(exc).__name__)
            logger.warning("run cancelled by signal")
        except Exception as exc:                               # noqa: BLE001
            status = "failed"
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            rw.emit_event("run_failed",
                          error_type=type(exc).__name__, message=str(exc))
            logger.exception("smoke run threw")
    finally:
        try:
            await env.close_async()
        except Exception as exc:                               # noqa: BLE001
            logger.warning("env.close_async failed: %s", exc)

    total_s = time.monotonic() - t0
    if trajectory is not None:
        try:
            rw.write_trajectory(trajectory)
        except Exception as exc:                               # noqa: BLE001
            logger.warning("write_trajectory failed: %s", exc)
    rw.write_eval_result(
        eval_status=eval_status,
        score=reward,
        eval_duration_s=eval_duration_s,
        error=eval_error,
    )
    rw.write_run_json({
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": {
            "name": "ale-claw", "version": deployer.version,
            "model": cfg.model,
            "config_repr": {
                "max_turns": cfg.max_turns, "timeout_s": cfg.timeout_s,
                "disabled_tools": cfg.disabled_tools,
            },
        },
        "task": {
            "slug": slug_task("demo/hello"),
            "path": "tasks/demo/hello",
            "variant_index": variant_index,
            "os_type": os_kind,
        },
        "env": {"provider": "static", "endpoint": profile["endpoint"]},
        "status": status, "score": reward,
        "termination": {
            "reason": status if status != "completed" else "completed",
            "error": (
                {"type": "Exception", "message": str(error), "traceback": error}
                if error else None
            ),
        },
        "timings": {"duration_s": round(total_s, 2)},
    })
    rw.emit_event("run_completed", status=status, score=reward,
                  total_duration_s=round(total_s, 2))
    rw.close()

    logger.info(
        "static_smoke_ale_claw %s done: status=%s reward=%s duration=%.1fs  →  %s",
        os_kind, status, reward, total_s, rw.run_dir,
    )

    # Sanity-check artifact landed
    origin_dir = rw.run_dir / "origin_log" / "ale-claw"
    if origin_dir.exists():
        n_files = sum(1 for p in origin_dir.rglob("*") if p.is_file())
        logger.info("origin_log: %d files at %s", n_files, origin_dir)

    return 0 if status == "completed" and (reward or 0) > 0 else 1


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("linux", "windows"):
        print(__doc__, file=sys.stderr)
        return 2
    os_kind = sys.argv[1]
    variant = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    return asyncio.run(run_once(os_kind, variant))


if __name__ == "__main__":
    raise SystemExit(main())
