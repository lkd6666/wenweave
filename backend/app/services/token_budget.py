"""Provider-neutral token accounting and bounded JSON tool responses."""
from __future__ import annotations

import json
from typing import Any

import tiktoken


def estimate_tokens(value: str) -> int:
    """Estimate tokens consistently across providers for budget enforcement."""
    if not value:
        return 0
    try:
        return len(tiktoken.get_encoding("cl100k_base").encode(value))
    except Exception:  # noqa: BLE001 - custom deployments must remain usable.
        return max(1, (len(value) + 2) // 3)


def truncate_to_tokens(value: str, max_tokens: int) -> str:
    """Return a text prefix that fits the configured token budget."""
    if max_tokens <= 0 or not value:
        return ""
    if estimate_tokens(value) <= max_tokens:
        return value
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(value[:middle]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    return value[:low].rstrip() + "…"


def bounded_json(
    value: Any,
    max_tokens: int,
    *,
    next_step: str,
    status: dict[str, Any] | None = None,
) -> str:
    """Serialize a structured tool report before the graph-level output store.

    ``ToolOutputStore`` now owns model-visible truncation because it needs the
    complete value and the provider's real ``tool_call_id`` to offer a durable
    continuation.  Keep this compatibility helper so existing tool bodies do
    not accidentally reintroduce lossy, per-tool truncation.
    """
    del max_tokens, next_step, status
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
