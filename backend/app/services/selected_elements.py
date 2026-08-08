"""Bounded, text-only context for elements selected in the editor."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

MAX_SELECTED_ELEMENT_COUNT = 12
MAX_SELECTED_ELEMENT_HTML_CHARS = 12_000
MAX_SELECTED_ELEMENTS_HTML_CHARS = 48_000
MAX_SELECTED_ELEMENT_TEXT_CHARS = 1_000
_TRUNCATION_MARKER = "\n<!-- selected element context truncated -->"

# Deliberately excludes quotes, tags and CSS closing parentheses so it can be
# used for HTML attributes and url(data:...) values without consuming markup.
INLINE_DATA_URI_PATTERN = re.compile(
    r"data:([a-z][a-z0-9+.-]{0,127}(?:/[a-z0-9+.-]+)?)(?:;[a-z0-9!#$&^_.+-]+)*,[^\"'<>)]*",
    re.IGNORECASE,
)


def redact_inline_data(value: str) -> str:
    return INLINE_DATA_URI_PATTERN.sub(
        lambda match: f"[inline {match.group(1).lower().split('/', 1)[0]} data omitted]",
        value,
    )


def _inline_data_identity(value: str) -> str:
    """Return the frontend-compatible FNV-1a fingerprint of embedded data."""
    hash_value = 0xCBF29CE484222325
    for byte in value.encode("utf-8"):
        hash_value ^= byte
        hash_value = (hash_value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{hash_value:016x}"


def redact_inline_data_for_identity(value: str) -> str:
    """Redact inline data while retaining a non-reversible stable identity."""
    return INLINE_DATA_URI_PATTERN.sub(
        lambda match: (
            f"[inline {match.group(1).lower().split('/', 1)[0]} "
            f"data identity:{_inline_data_identity(match.group(0))}]"
        ),
        value,
    )


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max(0, max_length - len(_TRUNCATION_MARKER))]}{_TRUNCATION_MARKER}"


def _normalize_locator(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    fingerprint = value.get("fingerprint")
    if not isinstance(fingerprint, Mapping):
        return None
    stable_attributes: dict[str, str] = {}
    raw_attributes = fingerprint.get("stable_attributes")
    if isinstance(raw_attributes, Mapping):
        for raw_key, raw_value in list(raw_attributes.items())[:16]:
            key = str(raw_key).lower().strip()
            if not re.fullmatch(r"(?:id|src|srcset|href|name|data-[a-z0-9_-]+)", key):
                continue
            stable_attributes[key] = redact_inline_data_for_identity(str(raw_value))[:2048]
    try:
        sibling_index = int(value.get("sibling_index", 0))
    except (TypeError, ValueError):
        sibling_index = 0
    return {
        "path": str(value.get("path", ""))[:1024],
        "parent_path": str(value.get("parent_path", ""))[:1024],
        "sibling_index": max(0, min(sibling_index, 10_000)),
        "fingerprint": {
            "tag_name": str(fingerprint.get("tag_name", ""))[:64],
            "stable_attributes": stable_attributes,
            "text": re.sub(r"\s+", " ", str(fingerprint.get("text", ""))).strip()[:MAX_SELECTED_ELEMENT_TEXT_CHARS],
        },
    }


def normalize_selected_element(value: Mapping[str, Any]) -> dict[str, Any]:
    html = redact_inline_data(str(value.get("html", "")))
    normalized: dict[str, Any] = {
        "selector": str(value.get("selector", ""))[:1024],
        "tag_name": str(value.get("tag_name", ""))[:64],
        "html": _truncate(html, MAX_SELECTED_ELEMENT_HTML_CHARS),
        "text": re.sub(r"\s+", " ", str(value.get("text", ""))).strip()[:MAX_SELECTED_ELEMENT_TEXT_CHARS],
    }
    locator = _normalize_locator(value.get("locator"))
    if locator:
        normalized["locator"] = locator
    return normalized


def normalize_selected_elements(values: Sequence[Mapping[str, Any]] | Any) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []

    normalized: list[dict[str, Any]] = []
    remaining_html_chars = MAX_SELECTED_ELEMENTS_HTML_CHARS
    for value in values[:MAX_SELECTED_ELEMENT_COUNT]:
        if not isinstance(value, Mapping) or remaining_html_chars <= 0:
            break
        item = normalize_selected_element(value)
        if not item["selector"] or not item["tag_name"] or not item["html"]:
            continue
        item["html"] = _truncate(item["html"], min(MAX_SELECTED_ELEMENT_HTML_CHARS, remaining_html_chars))
        normalized.append(item)
        remaining_html_chars -= len(item["html"])
    return normalized
