"""Sandbox-side entry. Invoked as a normal Python module:

    python -m ale_run.executors._sandbox_entry <spec_path>

inside the sandbox VM after :class:`SandboxExecutor` has scp'd the
``ale_run/`` source tree to the sandbox's ``ale_src_root`` and exported
that directory on ``PYTHONPATH``.

Reads ``<spec_path>`` (a JSON file the host wrote into the sandbox's
work_dir), reconstructs config + sandbox handle + a :class:`LocalExecutor`
in-sandbox, runs the deployer end-to-end, writes ``_result.json`` +
``_done.marker`` next to the spec for the host-side poller to read.

Symmetric with :mod:`_docker_entry`. No cua ``python_exec`` involved —
this is a normal Python process spawned via ``setsid`` (linux) or
``Start-Process`` (windows) by the host-side ``SandboxExecutor``.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import sys
import traceback
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("sandbox_entry")


def run(spec: dict) -> dict:
    """Drive ``install() + launch()`` of the deployer. Return result dict.

    Pure data in / out. Caught exceptions become ``ok=False`` with a
    full traceback so the host poller can surface them.
    """
    # Inject framework env vars (api keys, base URLs) so the deployer's
    # spawned subprocess inherits them.
    for k, v in (spec.get("env") or {}).items():
        os.environ[k] = v

    try:
        from ale_run.base_interface import SandboxHandle
        from ale_run.executors.local import LocalExecutor

        cfg_mod = importlib.import_module(spec["config_module"])
        dep_mod = importlib.import_module(spec["deployer_module"])
        cfg_cls = getattr(cfg_mod, spec["config_class"])
        dep_cls = getattr(dep_mod, spec["deployer_class"])

        cfg = cfg_cls(**spec["config_kwargs"])
        sandbox = SandboxHandle(**spec["sandbox_kwargs"])
        executor = LocalExecutor(
            config=cfg,
            work_dir=spec["work_dir"],
            sandbox=sandbox,
            env=spec.get("env") or {},
        )
        deployer = dep_cls(executor)

        loop = asyncio.new_event_loop()
        try:
            logger.info(
                "sandbox_entry: %s.install (work_dir=%s)",
                dep_cls.__name__, executor.work_dir,
            )
            loop.run_until_complete(deployer.install())
            timeout_s = float(spec.get("timeout_s") or 1800.0)
            logger.info(
                "sandbox_entry: %s.launch (timeout_s=%.0f)",
                dep_cls.__name__, timeout_s,
            )
            result = loop.run_until_complete(
                asyncio.wait_for(
                    deployer.launch(spec["prompt"]),
                    timeout=timeout_s,
                )
            )
        finally:
            loop.close()

        return {
            "ok": True,
            "status": result.status,
            "error": result.error,
            "transcript_path": result.transcript_path,
            "stderr_path": result.stderr_path,
            "pid": result.pid,
            "exit_code": result.exit_code,
            "duration_s": result.duration_s,
        }
    except Exception as exc:                                       # noqa: BLE001
        logger.exception("sandbox_entry crashed")
        return {
            "ok": False,
            "status": (
                "timeout" if isinstance(exc, asyncio.TimeoutError) else "failed"
            ),
            "error": f"sandbox_entry: {type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def main() -> int:
    """Read ``spec_path`` from argv, run, write ``_result.json`` +
    ``_done.marker`` into the work_dir specified in the spec."""
    if len(sys.argv) < 2:
        print(
            "usage: python -m ale_run.executors._sandbox_entry <spec_path>",
            file=sys.stderr,
        )
        return 2
    spec_path = Path(sys.argv[1])
    try:
        spec = json.loads(spec_path.read_text())
    except Exception as e:                                          # noqa: BLE001
        print(f"sandbox_entry: cannot read spec {spec_path}: {e}", file=sys.stderr)
        return 2

    out = run(spec)

    work_dir = Path(spec["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "_result.json").write_text(json.dumps(out, indent=2))
    # done.marker last — the host poller treats its presence as "result is
    # ready to read".
    (work_dir / "_done.marker").write_text("0\n" if out.get("ok") else "1\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
