"""Provider-neutral token accounting and bounded JSON tool responses."""
from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import tiktoken

logger = logging.getLogger(__name__)

# Use one multilingual encoding for provider-neutral estimates. Actual billing
# always uses provider-reported usage. Bundle the table so counting never needs
# a network request or a writable tiktoken cache directory.
_ENCODING_NAME = "o200k_base"
_BPE_HASH = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
_BPE_PATH = Path(__file__).resolve().parent.parent / "assets" / "tokenizers" / "o200k_base.tiktoken"
# Encoding definition from tiktoken 0.13.0's openai_public.o200k_base.
_PATTERN = "|".join([
    r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
    r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
    r"\p{N}{1,3}",
    r" ?[^\s\p{L}\p{N}]+[\r\n/]*",
    r"\s*[\r\n]+",
    r"\s+(?!\S)",
    r"\s+",
])


def _estimate_by_chars(value: str) -> int:
    ascii_chars = sum(1 for char in value if ord(char) < 128)
    non_ascii_chars = len(value) - ascii_chars
    return max(1, non_ascii_chars + (ascii_chars + 3) // 4)


@lru_cache(maxsize=1)
def _cached_encoding():
    """Load the verified local table once, without invoking tiktoken downloads."""
    try:
        contents = _BPE_PATH.read_bytes()
        if sha256(contents).hexdigest() != _BPE_HASH:
            raise ValueError("Bundled tokenizer table checksum mismatch")
        ranks = {}
        for line in contents.splitlines():
            token, rank = line.split()
            ranks[base64.b64decode(token, validate=True)] = int(rank)
        return tiktoken.Encoding(
            name=_ENCODING_NAME,
            pat_str=_PATTERN,
            mergeable_ranks=ranks,
            special_tokens={"<|endoftext|>": 199999, "<|endofprompt|>": 200018},
        )
    except Exception:  # noqa: BLE001 - damaged/missing assets must not stop editing.
        logger.warning("token_estimator_fallback encoding=%s reason=local_table_unavailable", _ENCODING_NAME)
        return None


def preload_tokenizer() -> None:
    """Initialize process-local counting before accepting model requests."""
    started = perf_counter()
    encoding = _cached_encoding()
    logger.warning(
        "token_estimator_ready encoding=%s source=%s load_ms=%.1f",
        encoding.name if encoding is not None else "characters",
        "bundled" if encoding is not None else "fallback",
        (perf_counter() - started) * 1000,
    )


def estimate_tokens(value: str) -> int:
    """Estimate tokens consistently across providers for budget enforcement."""
    if not value:
        return 0
    try:
        encoding = _cached_encoding()
        if encoding is None:
            return _estimate_by_chars(value)
        # Article text may contain literal special-token spellings. Count them
        # as ordinary text instead of raising and silently reverting to chars.
        return len(encoding.encode_ordinary(value))
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
        if estimate_tokens(value[:middle].rstrip() + "…") <= max_tokens:
            low = middle
        else:
            high = middle - 1
    return value[:low].rstrip() + "…" if low else ("…" if estimate_tokens("…") <= max_tokens else "")


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
