"""Force-timeout marker: writes a sentinel file the env can poll to self-cancel.

Ported from simprun/force_timeout.py. Not wired into the current
lifecycle — kept around for future use by an external operator tool.

Signatures take ``env: EnvHandle`` + an explicit ``run_id`` (was a
piggy-back field on the old ``RemoteVMConfig``; the merge into
``EnvHandle`` dropped it since the rest of the framework passes run_id
through separate args anyway).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..base_interface import EnvHandle
from .remote import LINUX_USER_HOME, run_remote, upload_file


FORCE_TIMEOUT_FILENAME = "ale_force_timeout.json"
WINDOWS_FORCE_TIMEOUT_PATH = rf"C:\Users\User\{FORCE_TIMEOUT_FILENAME}"
LINUX_FORCE_TIMEOUT_PATH = f"{LINUX_USER_HOME}/{FORCE_TIMEOUT_FILENAME}"
LOCAL_FORCE_TIMEOUT_DIR = Path(".force_timeouts")


def force_timeout_path(os_type: str) -> str:
    return LINUX_FORCE_TIMEOUT_PATH if os_type == "linux" else WINDOWS_FORCE_TIMEOUT_PATH


def local_force_timeout_path(run_id: str) -> Path:
    return LOCAL_FORCE_TIMEOUT_DIR / f"{run_id}.json"


def _write_local_force_timeout_request(run_id: str, payload: dict[str, Any]) -> Path:
    LOCAL_FORCE_TIMEOUT_DIR.mkdir(parents=True, exist_ok=True)
    path = local_force_timeout_path(run_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def clear_force_timeout_request(env: EnvHandle, *, run_id: str | None = None) -> None:
    if run_id:
        local_force_timeout_path(run_id).unlink(missing_ok=True)

    path = force_timeout_path(env.os)
    if env.is_linux:
        run_remote(env, f"rm -f '{path}'", timeout=5)
    else:
        run_remote(
            env,
            f"powershell -NoProfile -Command \""
            f"Remove-Item -Path '{path}' -Force -ErrorAction SilentlyContinue\"",
            timeout=5,
        )


def write_force_timeout_request(
    env: EnvHandle,
    *,
    task_id: str,
    run_id: str | None = None,
    reason: str = "manual_force_timeout",
    requested_by: str = "manager",
    extra: dict[str, Any] | None = None,
) -> str:
    path = force_timeout_path(env.os)
    payload = {
        "task_id": task_id,
        "reason": reason,
        "requested_by": requested_by,
        "requested_at": time.time(),
    }
    if extra:
        payload["extra"] = extra

    local_path: Path | None = None
    effective_run_id = run_id or (extra or {}).get("run_id")
    if effective_run_id:
        local_path = _write_local_force_timeout_request(str(effective_run_id), payload)

    try:
        upload_file(env, path, json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        if local_path is None:
            raise
        return str(local_path)
    return path


def force_timeout_requested(env: EnvHandle, *, run_id: str | None = None) -> bool:
    if run_id and local_force_timeout_path(run_id).exists():
        return True

    path = force_timeout_path(env.os)
    if env.is_linux:
        result = run_remote(env, f"test -f '{path}' && echo yes || true", timeout=5)
    else:
        result = run_remote(
            env,
            f"powershell -NoProfile -Command \""
            f"if (Test-Path '{path}') {{ 'yes' }}\"",
            timeout=5,
        )
    return result.returncode == 0 and "yes" in (result.stdout or "").strip().lower()
