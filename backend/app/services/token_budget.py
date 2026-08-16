"""Provider-neutral token accounting and bounded JSON tool responses."""
from __future__ import annotations

import json
import os
import tempfile
from functools import lru_cache
from hashlib import sha1, sha256
from typing import Any

import tiktoken

_CL100K_BPE_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
_CL100K_BPE_HASH = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
_ENCODING_NAME = "cl100k_base"


def _estimate_by_chars(value: str) -> int:
    ascii_chars = sum(1 for char in value if ord(char) < 128)
    non_ascii_chars = len(value) - ascii_chars
    return max(1, non_ascii_chars + (ascii_chars + 3) // 4)


def _tiktoken_cache_path() -> str | None:
    if "TIKTOKEN_CACHE_DIR" in os.environ:
        cache_dir = os.environ["TIKTOKEN_CACHE_DIR"]
    elif "DATA_GYM_CACHE_DIR" in os.environ:
        cache_dir = os.environ["DATA_GYM_CACHE_DIR"]
    else:
        cache_dir = os.path.join(tempfile.gettempdir(), "data-gym-cache")
    if cache_dir == "":
        return None
    return os.path.join(cache_dir, sha1(_CL100K_BPE_URL.encode()).hexdigest())


def _has_cached_cl100k_bpe() -> bool:
    cache_path = _tiktoken_cache_path()
    if not cache_path or not os.path.exists(cache_path):
        return False
    try:
        with open(cache_path, "rb", buffering=0) as file:
            return sha256(file.read()).hexdigest() == _CL100K_BPE_HASH
    except OSError:
        return False


def _is_encoding_loaded() -> bool:
    try:
        from tiktoken import registry

        return _ENCODING_NAME in registry.ENCODINGS
    except Exception:  # noqa: BLE001 - private registry access is best-effort.
        return False


@lru_cache(maxsize=1)
def _cached_encoding():
    if not _is_encoding_loaded() and not _has_cached_cl100k_bpe():
        return None
    return tiktoken.get_encoding(_ENCODING_NAME)


def estimate_tokens(value: str) -> int:
    """Estimate tokens consistently across providers for budget enforcement."""
    if not value:
        return 0
    try:
        encoding = _cached_encoding()
        if encoding is None:
            return _estimate_by_chars(value)
        return len(encoding.encode(value))
    except Exception:  # noqa: BLE001 - custom deployments must remain usable.
        return _estimate_by_chars(value)


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
