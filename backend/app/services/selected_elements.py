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


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max(0, max_length - len(_TRUNCATION_MARKER))]}{_TRUNCATION_MARKER}"


def normalize_selected_element(value: Mapping[str, Any]) -> dict[str, str]:
    html = redact_inline_data(str(value.get("html", "")))
    return {
        "selector": str(value.get("selector", ""))[:1024],
        "tag_name": str(value.get("tag_name", ""))[:64],
        "html": _truncate(html, MAX_SELECTED_ELEMENT_HTML_CHARS),
        "text": re.sub(r"\s+", " ", str(value.get("text", ""))).strip()[:MAX_SELECTED_ELEMENT_TEXT_CHARS],
    }


def normalize_selected_elements(values: Sequence[Mapping[str, Any]] | Any) -> list[dict[str, str]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []

    normalized: list[dict[str, str]] = []
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
