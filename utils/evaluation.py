"""Public evaluation helpers for demo tasks.

The public skeleton only includes evaluators that inspect agent-produced files
and other released task surfaces. Benchmark-private scoring logic belongs in a
separate non-public evaluation package until the project decides to release it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _remote_join(base: str, name: str) -> str:
    separator = "\\" if "\\" in base else "/"
    return base.rstrip("\\/") + separator + name


async def score_required_files(session, directory: str, filenames: list[str]) -> tuple[float, dict]:
    """Score a task by checking whether required files exist in a remote directory."""

    checks = []
    for filename in filenames:
        path = _remote_join(directory, filename)
        exists = bool(await session.exists(path))
        checks.append({"file": filename, "path": path, "exists": exists})

    score = sum(item["exists"] for item in checks) / len(checks) if checks else 0.0
    return score, {"directory": directory, "required_files": checks, "score": score}


def write_evaluation_json(details: dict, output_dir: str, task_tag: str) -> Path:
    """Write public evaluation details to a local JSON file."""

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out = Path(output_dir) / f"{task_tag}_evaluation_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(details, indent=2), encoding="utf-8")
    return out
