"""Compare document content without treating HTML serialization as an edit."""
from __future__ import annotations

import html5lib


def _serialized_document(html: str) -> str:
    document = html5lib.parse(html, treebuilder="dom")
    try:
        return html5lib.serialize(
            document,
            tree="dom",
            alphabetical_attributes=True,
            omit_optional_tags=False,
            quote_attr_values="always",
            minimize_boolean_attributes=False,
            strip_whitespace=False,
            resolve_entities=False,
        )
    finally:
        document.unlink()


def same_document_html(expected: str, actual: str) -> bool:
    """Keep text, whitespace, styles, URLs and SVG while normalizing HTML syntax.

    This comparison is only for conflict detection. Source revisions and tool
    offsets must continue to use the exact, unmodified source snapshot.
    """
    return expected == actual or _serialized_document(expected) == _serialized_document(actual)
