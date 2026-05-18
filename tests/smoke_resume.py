"""Unit smoke for resume / skip-completed.

No live VM. Builds fake run dirs with various status values; asserts
scan_completed_units + filter_completed return the right keys.

Run from repo root::

    uv run python tests/smoke_resume.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ale.runner.resume import filter_completed, scan_completed_units
from ale.runner.spec import AgentSpec, RunUnit


def _write_run_json(
    output_root: Path, *, agent_id: str, task_path: str,
    variant_index: int, status: str, ts: str = "20260101_000000",
) -> None:
    run_dir = (
        output_root / agent_id / "model-x"
        / task_path.replace("/", "__") / f"v{variant_index}" / ts
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "agent": {"id": agent_id},
        "task": {"path": f"tasks/{task_path}", "variant_index": variant_index},
        "status": status,
    }))


def _mk_unit(agent_id: str, task_path: str, vi: int) -> RunUnit:
    return RunUnit(
        agent_id=agent_id,
        agent_spec=AgentSpec(id=agent_id, class_="claude_code"),
        task_path=task_path,
        variant_index=vi,
    )


def test_scan_finds_completed_and_timeout() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _write_run_json(root, agent_id="a", task_path="demo/x", variant_index=0, status="completed")
        _write_run_json(root, agent_id="a", task_path="demo/x", variant_index=1, status="timeout")
        _write_run_json(root, agent_id="a", task_path="demo/y", variant_index=0, status="failed")
        _write_run_json(root, agent_id="b", task_path="demo/x", variant_index=0, status="cancelled")
        keys = scan_completed_units(root)
        # completed + timeout should be skipped; failed + cancelled re-run
        assert ("a", "demo/x", 0) in keys
        assert ("a", "demo/x", 1) in keys
        assert ("a", "demo/y", 0) not in keys
        assert ("b", "demo/x", 0) not in keys
        print("[scan] completed/timeout → terminal; failed/cancelled → re-run ✓")


def test_scan_empty_dir() -> None:
    with tempfile.TemporaryDirectory() as d:
        keys = scan_completed_units(Path(d))
        assert keys == set()
        print("[scan/empty] no run.json → empty set ✓")


def test_scan_missing_dir() -> None:
    keys = scan_completed_units(Path("/nonexistent/path/12345"))
    assert keys == set()
    print("[scan/missing] dir missing → empty set ✓")


def test_scan_latest_timestamp_wins() -> None:
    """If the same (agent,task,variant) has BOTH a completed run and a later
    failed run, the latest timestamp wins → don't skip (we want to re-attempt
    the latest known state, which is failed)."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _write_run_json(root, agent_id="a", task_path="demo/x", variant_index=0,
                        status="completed", ts="20260101_000000")
        _write_run_json(root, agent_id="a", task_path="demo/x", variant_index=0,
                        status="failed", ts="20260102_000000")
        keys = scan_completed_units(root)
        assert ("a", "demo/x", 0) not in keys, "latest=failed must override prior=completed"
        print("[scan/latest] latest run state wins (failed overrides prior completed) ✓")


def test_filter_splits() -> None:
    units = [
        _mk_unit("a", "demo/x", 0),
        _mk_unit("a", "demo/x", 1),
        _mk_unit("b", "demo/y", 0),
    ]
    completed = {("a", "demo/x", 0)}
    to_run, skipped = filter_completed(units, completed)
    assert len(to_run) == 2 and len(skipped) == 1
    assert skipped[0].agent_id == "a" and skipped[0].task_path == "demo/x" and skipped[0].variant_index == 0
    print("[filter] correctly splits to_run / skipped ✓")


def main() -> None:
    test_scan_finds_completed_and_timeout()
    test_scan_empty_dir()
    test_scan_missing_dir()
    test_scan_latest_timestamp_wins()
    test_filter_splits()
    print("\nsmoke OK ✓")


if __name__ == "__main__":
    main()
