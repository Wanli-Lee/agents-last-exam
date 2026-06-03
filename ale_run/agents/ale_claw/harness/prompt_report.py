"""System-prompt composition report (observability).

Split out of ``session.py`` (one of its four concerns). Measures total prompt
size, splits project vs non-project context, and catalogs injected files and
tool schemas. Duck-types tool objects to avoid importing BaseTool.

Based on OpenClaw's system prompt reporting for observability.
"""

from __future__ import annotations

import json
import time
from typing import Any


def build_system_prompt_report(
    *,
    system_prompt: str,
    context_files: list[Any] | None = None,
    tool_summaries: dict[str, str] | None = None,
    tools: list[Any] | None = None,
    source: str = "run",
) -> dict[str, Any]:
    """Build a report describing the system prompt composition.

    Measures total prompt size, splits project vs non-project context,
    catalogs injected files and tool schemas. Uses duck-typing for tool
    objects to avoid importing BaseTool.

    Based on OpenClaw's system prompt reporting for observability.
    """
    total_chars = len(system_prompt)

    # Split project vs non-project context at "# Project Context" header
    project_marker = "# Project Context"
    marker_pos = system_prompt.find(project_marker)
    if marker_pos >= 0:
        project_context_chars = total_chars - marker_pos
        non_project_context_chars = marker_pos
    else:
        project_context_chars = 0
        non_project_context_chars = total_chars

    # Injected files
    injected_files: list[dict[str, Any]] = []
    if context_files is not None:
        for cf in context_files:
            raw_content = getattr(cf, "content", "")
            raw_chars = len(raw_content) if raw_content else 0
            name = getattr(cf, "name", str(cf))

            # Measure how many chars actually appear in the prompt
            if raw_content and raw_content in system_prompt:
                injected_chars = len(raw_content)
            elif name in system_prompt:
                # Content was truncated; measure what's between file markers
                injected_chars = raw_chars  # fallback
            else:
                injected_chars = 0

            injected_files.append({
                "name": name,
                "raw_chars": raw_chars,
                "injected_chars": injected_chars,
                "truncated": injected_chars < raw_chars,
            })

    # Tools
    tool_entries: list[dict[str, Any]] = []
    if tools is not None:
        for tool in tools:
            name = getattr(tool, "name", str(tool))
            summary_chars = len(tool_summaries.get(name, "")) if tool_summaries else 0

            entry: dict[str, Any] = {"name": name, "summary_chars": summary_chars}

            # Duck-typed schema extraction
            if hasattr(tool, "parameters"):
                params = tool.parameters
                if isinstance(params, dict):
                    schema_str = json.dumps(params)
                    entry["schema_chars"] = len(schema_str)
                    props = params.get("properties", {})
                    entry["properties_count"] = len(props) if isinstance(props, dict) else 0
                else:
                    entry["schema_chars"] = 0
                    entry["properties_count"] = 0

            tool_entries.append(entry)
    elif tool_summaries is not None:
        for name, summary in tool_summaries.items():
            tool_entries.append({
                "name": name,
                "summary_chars": len(summary),
            })

    return {
        "source": source,
        "generated_at": time.time(),
        "system_prompt": {
            "chars": total_chars,
            "project_context_chars": project_context_chars,
            "non_project_context_chars": non_project_context_chars,
        },
        "injected_files": injected_files,
        "tools": {
            "entries": tool_entries,
        },
    }
