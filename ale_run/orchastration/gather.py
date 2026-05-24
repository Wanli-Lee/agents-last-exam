"""Post-launch bulk gather: pull ``src`` on the sandbox into ``dst`` on host.

Recursive walk via :meth:`SandboxHandle.list_dir`, per-file download via
:meth:`SandboxHandle.download_to_local` with bounded retries. Used by
the lifecycle's origin_log gather step (post-launch fanout).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..base_interface import SandboxHandle

logger = logging.getLogger(__name__)

_PER_FILE_RETRIES = 3
_RETRY_BACKOFFS_S = (1.0, 3.0, 9.0)


async def pull_dir(
    sandbox: SandboxHandle, *, src: str, dst: Path,
) -> dict:
    """Pull ``src`` (on sandbox) into ``dst`` (host). Best-effort per file.

    Return shape: ``{"transport": "cua", "files": int, "error": str | None}``.
    """
    dst.mkdir(parents=True, exist_ok=True)

    try:
        entries = await sandbox.list_dir(src)
    except Exception as e:                              # noqa: BLE001
        logger.warning("list_dir failed for %s: %s", src, e)
        return {"transport": "cua", "files": 0, "error": str(e)}

    if not entries:
        logger.info("gather.pull_dir: no entries at %s", src)
        return {"transport": "cua", "files": 0, "error": None}

    file_count = 0
    last_error: str | None = None
    sep = "/" if sandbox.is_linux else "\\"

    for entry in entries:
        rel = entry["relpath"]
        local = dst / rel.replace("\\", "/")
        if entry["is_dir"]:
            local.mkdir(parents=True, exist_ok=True)
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        remote_path = f"{src.rstrip(sep)}{sep}{rel.replace('/', sep)}"
        ok = await _download_with_retry(sandbox, remote_path, local)
        if ok:
            file_count += 1
        else:
            last_error = f"download failed: {rel}"
            logger.warning("gather.pull_dir: %s", last_error)

    return {"transport": "cua", "files": file_count, "error": last_error}


async def _download_with_retry(
    sandbox: SandboxHandle, remote_path: str, local: Path,
) -> bool:
    for attempt in range(_PER_FILE_RETRIES):
        try:
            ok = await sandbox.download_to_local(
                remote_path, str(local), timeout=120,
            )
        except Exception as e:                          # noqa: BLE001
            logger.debug(
                "download_to_local raised for %s (attempt %d): %s",
                remote_path, attempt + 1, e,
            )
            ok = False
        if ok:
            return True
        if attempt < _PER_FILE_RETRIES - 1:
            await asyncio.sleep(_RETRY_BACKOFFS_S[attempt])
    return False
