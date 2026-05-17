"""Container-side entry for the docker runtime.

Invoked by :class:`DockerExecutor` via ``python -m ale.runtime._docker_entry``
inside the container after ``uv sync --all-packages`` has installed ale
+ all its deps. Reads ``/work/_spec.json`` (mounted from host), constructs
:class:`DockerRuntime` + the deployer class, awaits ``install()`` +
``launch(prompt)``, writes results to ``/work/_result.json`` and a
``/work/_done.marker`` sentinel.

Distinct from :mod:`_vm_entry` (which is shipped via cua's python_exec
and has special source-generation constraints). Here we're a regular
module, can use ``from X import Y`` freely.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s")
logger = logging.getLogger("docker_entry")


SPEC_PATH = Path("/work/_spec.json")
RESULT_PATH = Path("/work/_result.json")
DONE_MARKER = Path("/work/_done.marker")


def _build_runtime(spec: dict):
    """Import DockerRuntime + config class, build them from spec."""
    from ale.runtime.docker import DockerRuntime
    cfg_mod = importlib.import_module(spec["config_module"])
    cfg_cls = getattr(cfg_mod, spec["config_class"])
    cfg = cfg_cls(**spec["config_kwargs"])
    return DockerRuntime(
        work_dir=Path(spec["work_dir"]),
        vm_endpoint=spec["vm_endpoint"],
        vm_os=spec["vm_os"],
        config=cfg,
    )


async def _run() -> dict:
    spec = json.loads(SPEC_PATH.read_text())
    runtime = _build_runtime(spec)
    dep_mod = importlib.import_module(spec["deployer_module"])
    dep_cls = getattr(dep_mod, spec["deployer_class"])
    deployer = dep_cls(runtime)
    logger.info("docker_entry: %s.install (work_dir=%s)", dep_cls.__name__, runtime.work_dir)
    await deployer.install()
    logger.info("docker_entry: %s.launch", dep_cls.__name__)
    result = await deployer.launch(spec["prompt"])
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


def main() -> int:
    try:
        out = asyncio.run(_run())
    except Exception as exc:                                    # noqa: BLE001
        logger.exception("docker_entry crashed")
        out = {
            "ok": False,
            "status": "failed",
            "error": f"docker_entry: {type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    RESULT_PATH.write_text(json.dumps(out, indent=2))
    DONE_MARKER.write_text("0\n" if out.get("ok") else "1\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
