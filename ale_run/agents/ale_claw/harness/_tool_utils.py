"""Shared validation/async helpers for the fs/shell/web tools.

These were duplicated (``_get_required_str``) or cross-imported from
``tools_fs`` (``_run_async``). Centralizing them here gives the tool modules a
single source of truth that doesn't tie them to one another.
"""

from __future__ import annotations

import asyncio
import concurrent.futures


def _run_async(coro):
    """Drive an async coroutine from a sync ``BaseTool.call``.

    Mirrors ``AnalyzeImageTool.call`` (analyze_image.py:149-170): spawn a
    fresh loop in a worker thread when one is already running, otherwise
    ``asyncio.run`` directly.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


def _get_required_str(params: dict, key: str, tool_name: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{tool_name}: required parameter "{key}" is missing or empty')
    return value
