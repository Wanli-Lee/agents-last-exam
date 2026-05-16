"""Unit smoke for ale_claw transcript → ALE Trajectory translation.

No real openclaw run, no LLM, no VM. Constructs a fake on-disk transcript
that mirrors the openclaw harness layout, runs the parser, asserts the
emitted Steps match the expected ATIF shape.

Run from repo root:
    uv run python tests/smoke_ale_claw_transcript.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ale.agents.ale_claw.transcript_to_trajectory import (
    _normalize_tool_result_content,
    parse_transcripts_into,
)
from ale.agents.trajectory import TrajectoryBuilder


def _build_fake_work_dir(tmp: Path) -> Path:
    """Mimic <work_dir>/openclaw_sessions/<task_id>/{transcript.jsonl, state.json}."""
    sessions = tmp / "openclaw_sessions" / "demo__hello"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "state.json").write_text(json.dumps({
        "total_tokens": {"input_tokens": 1234, "output_tokens": 56},
    }))
    transcript = [
        # Session header (skipped by parser).
        {"type": "session", "id": "sess-0", "task_id": "demo__hello", "model": "x"},

        # Turn 1 — assistant: text + function_call (one Step expected).
        {"type": "message", "id": "m1", "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I will write the file."},
                {"type": "function_call", "id": "call-1", "name": "write",
                 "arguments": json.dumps({"path": "/tmp/x", "data": "hello"})},
            ],
            "usage": {"input": 100, "output": 20, "total": 120, "cost": 0.001},
            "stopReason": "tool_use",
        }},

        # Turn 1 — tool reply (one environment Step expected).
        {"type": "message", "id": "m2", "message": {
            "role": "tool",
            "content": [
                # Python-repr content — should be re-serialized as JSON.
                {"type": "tool_result", "tool_use_id": "call-1",
                 "content": "{'success': True, 'bytes_written': 5}"},
            ],
        }},

        # Turn 2 — assistant: thinking + text (one Step with both).
        {"type": "message", "id": "m3", "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "User wanted hello world; done."},
                {"type": "text", "text": "**DONE**"},
            ],
            "usage": {"input": 130, "output": 12, "total": 142, "cost": 0.0008},
            "stopReason": "end_turn",
        }},

        # Compaction entry — non-message, parser ignores.
        {"type": "compaction", "id": "comp-1", "summary": "..."},

        # Empty/zero-content assistant message — parser should skip silently.
        {"type": "message", "id": "m4", "message": {
            "role": "assistant", "content": [],
        }},
    ]
    (sessions / "transcript.jsonl").write_text(
        "\n".join(json.dumps(e) for e in transcript) + "\n",
    )
    return tmp


def test_normalize_tool_result_content() -> None:
    """Python-repr → JSON; pass-through for non-repr / non-collection inputs."""
    assert _normalize_tool_result_content("{'a': 1}") == '{\n  "a": 1\n}'
    assert _normalize_tool_result_content("[1, 2, 3]") == "[\n  1,\n  2,\n  3\n]"
    assert _normalize_tool_result_content("plain text") == "plain text"
    assert _normalize_tool_result_content(None) == ""
    assert _normalize_tool_result_content({"a": 1}) == '{"a": 1}'
    assert _normalize_tool_result_content("{not parsable") == "{not parsable"
    print("[normalize] ok")


def test_parse_full_transcript() -> None:
    with tempfile.TemporaryDirectory() as td:
        work_dir = _build_fake_work_dir(Path(td))
        builder = TrajectoryBuilder(
            agent_name="ale-claw",
            agent_version="test",
            model="openrouter/anthropic/claude-sonnet-4-20250514",
            task_path="demo/hello",
            variant_index=0,
        )
        parse_transcripts_into(work_dir, builder)
        traj = builder.trajectory

    sources = [s.source for s in traj.steps]
    print(f"[parse] step sources: {sources}")
    # Expected:
    #   m1 → 1 agent Step (text + tool_call)
    #   m2 → 1 environment Step (tool_result)
    #   m3 → 1 agent Step (thinking + text)
    #   m4 → SKIP (empty content)
    assert sources == ["agent", "environment", "agent"], f"got {sources}"

    # m1: assistant with text + function_call merged into one Step.
    s1 = traj.steps[0]
    assert s1.message == "I will write the file."
    assert len(s1.tool_calls) == 1
    assert s1.tool_calls[0].name == "write"
    assert s1.tool_calls[0].arguments == {"path": "/tmp/x", "data": "hello"}
    assert s1.tool_calls[0].id == "call-1"
    assert s1.metrics is not None
    assert s1.metrics.input_tokens == 100
    assert s1.metrics.output_tokens == 20
    assert s1.metrics.cost_usd == 0.001
    assert s1.extra.get("stop_reason") == "tool_use"

    # m2: tool_result → environment Step. Content re-serialized as JSON.
    s2 = traj.steps[1]
    assert s2.observation is not None
    assert len(s2.observation.results) == 1
    tr = s2.observation.results[0]
    assert tr.tool_call_id == "call-1"
    assert len(tr.content) == 1
    assert tr.content[0].type == "text"
    parsed = json.loads(tr.content[0].text)
    assert parsed == {"success": True, "bytes_written": 5}
    assert tr.is_error is False

    # m3: thinking → reasoning, text → message.
    s3 = traj.steps[2]
    assert s3.message == "**DONE**"
    assert s3.reasoning == "User wanted hello world; done."
    assert s3.tool_calls == []
    assert s3.metrics is not None
    assert s3.metrics.input_tokens == 130

    # Aggregated usage from state.json → trajectory.extra
    assert "ale_claw" in traj.extra
    usage = traj.extra["ale_claw"]["usage"]
    assert usage["overall_input_tokens"] == 1234         # state.json wins over msg-sum
    assert usage["output_tokens"] == 56                  # state.json wins
    assert usage["uncached_input_tokens"] == 1234        # no cache files → uncached = overall
    assert usage["total_cost_usd"] == round(0.001 + 0.0008, 6)

    # raw_transcript path surfaced
    assert traj.extra["ale_claw"]["raw_transcript"].endswith("transcript.jsonl")
    print("[parse] full transcript ok — 3 steps, metrics + aggregates correct")


def test_parse_empty_workdir() -> None:
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        # No openclaw_sessions/ dir at all
        builder = TrajectoryBuilder(
            agent_name="ale-claw",
            agent_version="test",
            model="x",
            task_path="demo/hello",
            variant_index=0,
        )
        parse_transcripts_into(work_dir, builder)
        traj = builder.trajectory
    assert len(traj.steps) == 1
    assert traj.steps[0].source == "system"
    assert "no_transcript" in traj.steps[0].extra.get("reason", "")
    print("[parse] empty workdir → single system step ok")


def main() -> int:
    test_normalize_tool_result_content()
    test_parse_full_transcript()
    test_parse_empty_workdir()
    print("\nsmoke OK ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
