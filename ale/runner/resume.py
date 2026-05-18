"""Resume / skip-completed by experiment name.

Two runs of the same ``ExperimentSpec.name`` share an ``output_root``
prefix (``<spec.output.root>/<spec.name>/``). When ``force_rerun=False``
(the default), the Runner scans prior run.json files under that prefix
and skips units whose previous attempt reached a terminal state.

Terminal states (skipped):
  - ``completed`` — solved (or finished at step budget)
  - ``timeout``   — agent exceeded wall budget

Non-terminal (re-attempted):
  - ``failed``    — re-run; usually transient (rate-limit, GCP flutter)
  - ``cancelled`` — user-interrupted; re-run
  - any unknown / missing run.json — re-run

Pure scan; no log merging. The new run still gets a fresh timestamp dir.
Operators integrate results manually across timestamp dirs after batch.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .spec import RunUnit

logger = logging.getLogger(__name__)


# Per user instruction: completed AND timeout both skip. Failed / cancelled re-run.
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "timeout"})


def scan_completed_units(output_root: Path) -> set[tuple[str, str, int]]:
    """Walk ``output_root`` for ``run.json`` files. Return the set of
    ``(agent_id, task_path, variant_index)`` keys whose status is terminal.

    Layout walked (matches :class:`RunWriter`):
      ``<output_root>/<agent>/<model>/<task_slug>/v<i>/<ts>/run.json``

    Multiple timestamp dirs per (agent, task, variant) is fine — the
    most-recent one's status wins (we read all but the latest takes
    precedence on conflict).
    """
    completed: dict[tuple[str, str, int], tuple[str, str]] = {}  # key → (timestamp, status)
    if not output_root.exists():
        return set()
    for run_json in output_root.rglob("run.json"):
        try:
            data = json.loads(run_json.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("resume: skipping unreadable run.json at %s: %s", run_json, exc)
            continue
        agent_id = (data.get("agent") or {}).get("id")
        task = data.get("task") or {}
        task_path = task.get("path") or ""
        # Strip the "tasks/" prefix that _build_run_json adds.
        if task_path.startswith("tasks/"):
            task_path = task_path[len("tasks/"):]
        variant_index = task.get("variant_index")
        status = data.get("status")
        if not agent_id or not task_path or variant_index is None or not status:
            continue
        key = (agent_id, task_path, int(variant_index))
        # Timestamp from run dir name (parent of run.json).
        ts = run_json.parent.name
        prior = completed.get(key)
        if prior is None or ts > prior[0]:
            completed[key] = (ts, status)
    return {k for k, (_ts, status) in completed.items() if status in TERMINAL_STATUSES}


def filter_completed(
    units: list[RunUnit], completed_keys: set[tuple[str, str, int]],
) -> tuple[list[RunUnit], list[RunUnit]]:
    """Split ``units`` into (to_run, skipped) by membership in ``completed_keys``."""
    to_run: list[RunUnit] = []
    skipped: list[RunUnit] = []
    for u in units:
        if (u.agent_id, u.task_path, u.variant_index) in completed_keys:
            skipped.append(u)
        else:
            to_run.append(u)
    return to_run, skipped
