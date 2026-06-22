"""Pull the agent's output off the sandbox after the run.

Dispatched by the lifecycle on ``artifacts_path.output_path``:

  None         → skip; output stays on the sandbox and is lost on teardown
  ``"local"``  → :func:`pull_to_host` (cua HTTP, one file at a time)
  ``"gs://X"`` → :func:`push_to_gcs` (VM-side gsutil; nothing on host)
"""
from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Any

from ..base_interface import SandboxHandle, TaskDataSpec

logger = logging.getLogger(__name__)


def _output_dir(sandbox: SandboxHandle, task_data: TaskDataSpec) -> str:
    sep = "/" if sandbox.is_linux else "\\"
    return sep.join([
        sandbox.task_data_root.rstrip("/\\"),
        task_data.domain_name,
        task_data.task_name,
        task_data.variant_name,
        "output",
    ])


async def pull_to_host(
    sandbox: SandboxHandle, task_data: TaskDataSpec, *, dest_dir: Path,
) -> dict[str, Any]:
    """``output_path == 'local'`` — walk + per-file download to host run dir."""
    src = _output_dir(sandbox, task_data)
    entries = await sandbox.list_dir(src)
    if not entries:
        return {"skipped": True, "reason": "empty_or_missing", "vm_path": src}

    dest_dir.mkdir(parents=True, exist_ok=True)
    sep = "/" if sandbox.is_linux else "\\"
    files = 0
    total_bytes = 0
    errors: list[dict[str, str]] = []
    for entry in entries:
        rel = entry["relpath"]
        if entry.get("is_dir"):
            (dest_dir / rel.replace("\\", "/")).mkdir(parents=True, exist_ok=True)
            continue
        remote_path = f"{src.rstrip(sep)}{sep}{rel}"
        local_path = dest_dir / rel.replace("\\", "/")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        ok = await sandbox.download_to_local(remote_path, str(local_path), timeout=120)
        if ok:
            files += 1
            try:
                total_bytes += local_path.stat().st_size
            except OSError:
                pass
        else:
            errors.append({"vm_path": remote_path, "error": "download_failed"})
            marker = local_path.with_suffix(local_path.suffix + ".unreadable")
            marker.write_text(f"vm_path={remote_path}\nreason=download_failed\n")

    logger.info(
        "pull_to_host: %s → %s (files=%d bytes=%d errors=%d)",
        src, dest_dir, files, total_bytes, len(errors),
    )
    return {
        "transport": "cua",
        "vm_path": src,
        "files": files,
        "bytes": total_bytes,
        "errors": errors,
    }


async def push_dir_to_sandbox(
    sandbox: SandboxHandle, task_data: TaskDataSpec, *, src_dir: Path,
) -> dict[str, Any]:
    """Reverse of :func:`pull_to_host`: re-stage a host ``output/`` tree back
    into the sandbox's in-container output dir.

    Used by ``--eval-only`` (rejudge): a prior run's saved
    ``<run_dir>/output/`` is uploaded to the same in-container path the
    verifier reads from, so ``evaluate()`` can grade it without re-running the
    agent. ``.unreadable`` marker files (written by :func:`pull_to_host` on a
    failed pull) are skipped — they are not real agent outputs.
    """
    dst = _output_dir(sandbox, task_data)
    sep = "/" if sandbox.is_linux else "\\"
    files = 0
    total_bytes = 0
    errors: list[dict[str, str]] = []
    await sandbox.mkdir(dst)
    for local_path in sorted(p for p in src_dir.rglob("*") if p.is_file()):
        if local_path.suffix == ".unreadable":
            continue
        rel = local_path.relative_to(src_dir).as_posix()
        remote_path = f"{dst.rstrip(sep)}{sep}{rel.replace('/', sep)}"
        parent = remote_path.rsplit(sep, 1)[0]
        try:
            await sandbox.mkdir(parent)
            await sandbox.upload_local_file(str(local_path), remote_path)
            files += 1
            try:
                total_bytes += local_path.stat().st_size
            except OSError:
                pass
        except Exception as e:  # noqa: BLE001 — best-effort, report per file
            errors.append({"local_path": str(local_path), "error": str(e)})

    logger.info(
        "push_dir_to_sandbox: %s → %s (files=%d bytes=%d errors=%d)",
        src_dir, dst, files, total_bytes, len(errors),
    )
    return {
        "transport": "cua",
        "vm_path": dst,
        "files": files,
        "bytes": total_bytes,
        "errors": errors,
    }


async def push_to_gcs(
    sandbox: SandboxHandle, task_data: TaskDataSpec, *,
    run_id: str, bucket: str,
) -> dict[str, Any]:
    """``output_path == 'gs://...'`` — VM-side gsutil push.

    cp -r preserves the trailing src dir name (``output``) under dst, so
    dst is the run prefix; final landing is ``<bucket>/<run_id>/output/``.

    Uses ``gsutil`` with the injected SA key (via ``_gsutil`` — same path the
    read/staging side uses) rather than ``gcloud storage cp``. The VMs carry NO
    baked credential: ``gcloud``'s ambient auth falls back to the GCE metadata
    SA, which isn't provisioned on these images, so ``gcloud storage cp`` fails
    with a metadata-server token error. The injected key authenticates writes
    consistently with reads.
    """
    from .task_data.gsbucket import _gsutil

    src = _output_dir(sandbox, task_data)
    run_prefix = f"{bucket.rstrip('/')}/{run_id}/"
    gcs_dst = f"{run_prefix}output/"
    gsutil = _gsutil(sandbox)

    if sandbox.is_linux:
        cmd = f"{gsutil} -m cp -r {shlex.quote(src)} {shlex.quote(run_prefix)}"
    else:
        cmd = (
            'powershell -NoProfile -Command "'
            f"{gsutil} -m cp -r '{src}' '{run_prefix}'"
            '"'
        )
    logger.info("push_to_gcs: %s → %s", src, gcs_dst)
    r = await sandbox.run_command(cmd, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(
            f"gsutil cp failed (rc={r.returncode}): "
            f"{(r.stderr or '')[:300]}"
        )
    return {"transport": "gcs", "gcs_path": gcs_dst}
