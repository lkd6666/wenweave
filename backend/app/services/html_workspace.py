"""Source-preserving HTML workspace for the editor Agent.

The workspace deliberately never serialises a parsed DOM back to HTML.  It
uses ``HTMLParser`` only to build a block index over the original source, then
applies validated edits to the original character ranges.  This keeps WeChat
markup, inline styles and image data untouched unless a tool explicitly edits
that block.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from urllib.parse import urlparse
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from typing import Callable, Iterable, Literal, Mapping

from app.core.token_budgets import DEFAULT_TOOL_RESULT_MAX_TOKENS
from app.services.token_budget import estimate_tokens
from app.services.selected_elements import MAX_SELECTED_ELEMENT_TEXT_CHARS, redact_inline_data_for_identity

BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "div",
    "figure",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "img",
    "li",
    "main",
    "ol",
    "p",
    "section",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
MAX_MAP_BLOCKS = 72
MAX_SEARCH_RESULTS = 12
MAX_IMAGE_RESULTS = 12
MAX_READ_BLOCKS = 16
MAX_PATCH_OPERATIONS = 64

_SAFE_SEARCH_ATTRIBUTES = ("id", "class", "data-role", "role", "style", "alt", "title", "aria-label")
_IMAGE_CONTEXT_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "figcaption", "td", "th"}
_IMAGE_CONTEXT_TEXT_LIMIT = 140
_SECTION_LABEL_PATTERN = re.compile(
    r"^(?:第\s*[一二三四五六七八九十百千万\d]+\s*[章节部分]|[一二三四五六七八九十百千万]+\s*[、.]|\d+\s*[、.]|附件(?:\s*[一二三四五六七八九十\d]+)?\s*[：:]?)"
)

PatchMode = Literal["replace_outer", "replace_inner", "insert_before", "insert_after", "delete"]


class WorkspaceError(ValueError):
    """A user-correctable Agent workspace error with structured diagnostics."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


@dataclass
class HtmlNode:
    tag: str
    start: int
    open_end: int
    parent: "HtmlNode | None"
    attrs: dict[str, str] = field(default_factory=dict)
    path: str = ""
    close_start: int | None = None
    end: int | None = None
    children: list["HtmlNode"] = field(default_factory=list)
    child_tag_counts: dict[str, int] = field(default_factory=dict)

    @property
    def is_void(self) -> bool:
        return self.tag in VOID_TAGS


@dataclass(frozen=True)
class HtmlBlock:
    block_id: str
    tag: str
    start: int
    open_end: int
    close_start: int
    end: int
    path: str
    heading_path: tuple[str, ...]
    text: str
    attributes: str
    has_image: bool
    has_table: bool
    expected_hash: str
    searchable: str

    def map_item(self) -> dict:
        return {
            "block_id": self.block_id,
            "tag": self.tag,
            "path": self.path,
            "heading_path": list(self.heading_path),
            "text": self.text,
            "attributes": self.attributes,
            "has_image": self.has_image,
            "has_table": self.has_table,
            "expected_hash": self.expected_hash,
        }


@dataclass(frozen=True)
class BlockIdentityLocator:
    """A run-local, content-backed identity for cautiously carrying a block forward."""

    block_id: str
    tag: str
    expected_hash: str
    attributes: str
    heading_path: tuple[str, ...]
    text: str

    @property
    def key(self) -> tuple[str, str, str, tuple[str, ...]]:
        # The full source hash is the primary identity. Attributes and heading
        # context make a copied, structurally moved block much less likely to
        # be mistaken for its predecessor.
        return self.tag, self.expected_hash, self.attributes, self.heading_path


@dataclass(frozen=True)
class SelectionResolution:
    """Current-document resolution for a user-selected DOM node."""

    status: Literal["exact", "relocated", "ambiguous", "missing"]
    block: HtmlBlock | None = None
    reason: str = ""
    target_tag: str = ""
    target_path: str = ""
    target_text: str = ""

    @property
    def block_id(self) -> str:
        return self.block.block_id if self.block else ""

    @property
    def tag(self) -> str:
        return self.target_tag or (self.block.tag if self.block else "")

    @property
    def path(self) -> str:
        return self.target_path or (self.block.path if self.block else "")

    @property
    def text(self) -> str:
        return self.target_text or (self.block.text if self.block else "")

    @property
    def expected_hash(self) -> str:
        return self.block.expected_hash if self.block else ""

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "block_id": self.block_id,
            "tag": self.tag,
            "path": self.path,
            "text": self.text,
            "reason": self.reason,
        }


class _SourceParser(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = self._line_offsets(source)
        self.roots: list[HtmlNode] = []
        self.stack: list[HtmlNode] = []
        self._root_tag_counts: dict[str, int] = {}

    @staticmethod
    def _line_offsets(value: str) -> list[int]:
        offsets = [0]
        for index, char in enumerate(value):
            if char == "\n":
                offsets.append(index + 1)
        return offsets

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[min(max(line - 1, 0), len(self.line_offsets) - 1)] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        start = self.source_offset()
        raw = self.get_starttag_text() or ""
        parent = self.stack[-1] if self.stack else None
        sibling_counts = parent.child_tag_counts if parent else self._root_tag_counts
        sibling_counts[tag] = sibling_counts.get(tag, 0) + 1
        path_part = f"{tag}:nth-of-type({sibling_counts[tag]})"
        node = HtmlNode(
            tag=tag,
            start=start,
            open_end=start + len(raw),
            parent=parent,
            attrs={key.lower(): value or "" for key, value in attrs},
            path=f"{parent.path} > {path_part}" if parent else path_part,
        )
        if node.parent:
            node.parent.children.append(node)
        else:
            self.roots.append(node)
        if node.is_void:
            node.close_start = node.open_end
            node.end = node.open_end
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag.lower():
            node = self.stack.pop()
            node.close_start = node.open_end
            node.end = node.open_end

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        match_index = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index].tag == tag), None)
        if match_index is None:
            return
        start = self.source_offset()
        closing_end = self.source.find(">", start)
        end = len(self.source) if closing_end < 0 else closing_end + 1
        # Invalid, unclosed descendants end before the matching closing tag.
        for node in self.stack[match_index + 1 :]:
            node.close_start = start
            node.end = start
        node = self.stack[match_index]
        node.close_start = start
        node.end = end
        del self.stack[match_index:]

    def close_open_nodes(self) -> None:
        for node in self.stack:
            node.close_start = len(self.source)
            node.end = len(self.source)
        self.stack = []


def _normalise_text(value: str, limit: int = 240) -> str:
    plain = re.sub(r"<[^>]+>", " ", value)
    plain = re.sub(r"\s+", " ", html_lib.unescape(plain)).strip()
    return plain[:limit]


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


class HtmlWorkspace:
    """A revision-local index and patch engine over one HTML source string."""

    def __init__(
        self,
        source_html: str,
        redact: Callable[[str], str] | None = None,
        tool_result_max_tokens: int = DEFAULT_TOOL_RESULT_MAX_TOKENS,
        block_id_overrides: Mapping[tuple[int, int, str, str], str] | None = None,
        stale_block_hints: Mapping[str, str] | None = None,
    ):
        self.source_html = source_html
        self._redact = redact or (lambda value: value)
        self.tool_result_max_tokens = max(1, int(tool_result_max_tokens))
        self._block_id_overrides = dict(block_id_overrides or {})
        self._reused_block_ids: set[str] = set()
        self._stale_block_hints = {
            str(block_id): _normalise_text(str(text), 120)
            for block_id, text in (stale_block_hints or {}).items()
            if str(block_id) and str(text).strip()
        }
        # Initialise session-scoped inline-data placeholders once without
        # retaining a second full-document copy alongside source_html.
        self._redact(source_html)
        # Hashes are opaque identifiers, not model-visible source. Hash the
        # original value so two different inline data URIs cannot collapse to
        # the same redacted revision or block hash.
        self.revision = self.revision_for(source_html)
        parser = _SourceParser(source_html)
        parser.feed(source_html)
        parser.close()
        parser.close_open_nodes()
        self._line_offsets = parser.line_offsets
        self._nodes = list(self._walk(parser.roots))
        self._nodes_by_start = {node.start: node for node in self._nodes}
        self.blocks = self._build_blocks()
        self._refresh_block_indexes()

    def _refresh_block_indexes(self) -> None:
        self._blocks_by_id = {block.block_id: block for block in self.blocks}
        self._blocks_by_start = {block.start: block for block in self.blocks}

    @staticmethod
    def revision_for(source_html: str) -> str:
        return _safe_hash(source_html)

    @staticmethod
    def _walk(nodes: Iterable[HtmlNode]) -> Iterable[HtmlNode]:
        for node in nodes:
            yield node
            yield from HtmlWorkspace._walk(node.children)

    def _line_for_offset(self, offset: int) -> int:
        # Binary search avoids importing a parser solely for source position.
        low, high = 0, len(self._line_offsets)
        while low < high:
            middle = (low + high) // 2
            if self._line_offsets[middle] <= offset:
                low = middle + 1
            else:
                high = middle
        return max(1, low)

    def _attributes(self, node: HtmlNode) -> str:
        values: list[str] = []
        for key in _SAFE_SEARCH_ATTRIBUTES:
            value = self._redact(node.attrs.get(key, "")).strip()
            if not value:
                continue
            value = re.sub(r"\s+", " ", value)
            if key == "style":
                value = value[:120]
            else:
                value = value[:160]
            values.append(f'{key}="{value}"')
        return " ".join(values)[:260]

    def _block_id_for(self, node: HtmlNode, expected_hash: str) -> str:
        key = (node.start, node.end or node.start, node.tag, expected_hash)
        inherited = self._block_id_overrides.get(key, "")
        if inherited and inherited not in self._reused_block_ids:
            self._reused_block_ids.add(inherited)
            return inherited
        return f"b-{self.revision[:8]}-{node.start:x}-{node.tag}"

    def _build_blocks(self) -> list[HtmlBlock]:
        heading_stack: list[str] = []
        blocks: list[HtmlBlock] = []
        for node in self._nodes:
            if node.end is None or node.close_start is None or node.tag not in BLOCK_TAGS:
                continue
            raw = self.source_html[node.start : node.end]
            safe = self._redact(raw)
            text = _normalise_text(safe)
            if node.tag in {"style", "script"}:
                continue
            if re.fullmatch(r"h[1-6]", node.tag):
                level = int(node.tag[1])
                heading_stack = heading_stack[: level - 1]
                if text:
                    heading_stack.append(text[:120])
            attributes = self._attributes(node)
            path = node.path
            expected_hash = _safe_hash(raw)
            block_id = self._block_id_for(node, expected_hash)
            blocks.append(
                HtmlBlock(
                    block_id=block_id,
                    tag=node.tag,
                    start=node.start,
                    open_end=node.open_end,
                    close_start=node.close_start,
                    end=node.end,
                    path=path,
                    heading_path=tuple(heading_stack),
                    text=text,
                    attributes=attributes,
                    has_image="<img" in safe.lower(),
                    has_table="<table" in safe.lower(),
                    expected_hash=expected_hash,
                    searchable=" ".join((node.tag, path, attributes, " ".join(heading_stack), text)).lower(),
                )
            )
        return blocks

    def identity_locators(self) -> list[BlockIdentityLocator]:
        """Expose only enough metadata for a same-run identity reconciliation."""
        return [
            BlockIdentityLocator(
                block_id=block.block_id,
                tag=block.tag,
                expected_hash=block.expected_hash,
                attributes=block.attributes,
                heading_path=block.heading_path,
                text=block.text,
            )
            for block in self.blocks
        ]

    @property
    def reused_block_id_count(self) -> int:
        return len(self._reused_block_ids)

    def reuse_unique_block_identities(self, locators: Iterable[BlockIdentityLocator]) -> int:
        """Carry an old ID to one uniquely identical current block.

        Exact offset translation is applied before this method. This fallback
        only accepts a one-to-one full-source hash plus safe context match,
        so duplicate text or copied markup remains intentionally unresolved.
        """
        prior_by_key: dict[tuple[str, str, str, tuple[str, ...]], list[BlockIdentityLocator]] = {}
        for locator in locators:
            if locator.block_id in self._reused_block_ids:
                continue
            prior_by_key.setdefault(locator.key, []).append(locator)

        current_by_key: dict[tuple[str, str, str, tuple[str, ...]], list[HtmlBlock]] = {}
        for block in self.blocks:
            if block.block_id in self._reused_block_ids:
                continue
            key = (block.tag, block.expected_hash, block.attributes, block.heading_path)
            current_by_key.setdefault(key, []).append(block)

        replacements: dict[str, str] = {}
        occupied_ids = {block.block_id for block in self.blocks}
        for key, previous in prior_by_key.items():
            candidates = current_by_key.get(key, [])
            if len(previous) != 1 or len(candidates) != 1:
                continue
            old_id = previous[0].block_id
            candidate = candidates[0]
            if old_id in occupied_ids:
                continue
            replacements[candidate.block_id] = old_id
            occupied_ids.add(old_id)

        if not replacements:
            return 0
        self.blocks = [replace(block, block_id=replacements.get(block.block_id, block.block_id)) for block in self.blocks]
        self._reused_block_ids.update(replacements.values())
        self._refresh_block_indexes()
        return len(replacements)

    def _fit_index_items(
        self,
        *,
        kind: str,
        items: list[dict],
        payload: dict,
        requested_count: int,
        tool_result_max_tokens: int | None = None,
    ) -> dict:
        """Shrink directory/search lists at whole-item boundaries.

        Unlike source reads, index rows can safely be omitted.  The response
        tells the model what happened so it can issue a narrower search.
        """
        budget = self._result_token_limit(tool_result_max_tokens)
        selected: list[dict] = []
        for item in items[:requested_count]:
            candidate = {**payload, kind: [*selected, item]}
            if estimate_tokens(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) > budget:
                break
            selected.append(item)
        omitted = max(0, len(items) - len(selected))
        if omitted:
            metadata = {
                "truncated": True,
                "omitted_count": omitted,
                "returned_tokens_limit": budget,
                "next_step": "请使用更具体的关键词搜索，或分批读取候选排版块。",
            }
            # The truncation metadata itself costs tokens. Remove full rows
            # until the final JSON (not merely its pre-metadata form) fits.
            while selected:
                result = {**payload, kind: selected, **metadata}
                if estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= budget:
                    break
                selected.pop()
                metadata["omitted_count"] = len(items) - len(selected)
            result = {**payload, kind: selected, **metadata}
        else:
            result = {**payload, kind: selected}
        return result

    def _result_token_limit(self, value: int | None) -> int:
        return max(1, int(self.tool_result_max_tokens if value is None else value))

    def map_payload(self, limit: int = MAX_MAP_BLOCKS, tool_result_max_tokens: int | None = None) -> dict:
        priority = sorted(
            self.blocks,
            key=lambda block: (
                0 if block.tag.startswith("h") else 1,
                0 if block.tag in {"section", "article", "figure", "table"} else 1,
                block.start,
            ),
        )
        requested = max(1, min(limit, MAX_MAP_BLOCKS))
        return self._fit_index_items(
            kind="blocks",
            items=[block.map_item() for block in priority],
            payload={
            "revision": self.revision,
            "block_count": len(self.blocks),
            },
            requested_count=requested,
            tool_result_max_tokens=tool_result_max_tokens,
        )

    def _searchable(self, block: HtmlBlock) -> str:
        return block.searchable

    def search(
        self,
        query: str,
        limit: int = 8,
        cursor: int = 0,
        tool_result_max_tokens: int | None = None,
    ) -> dict:
        query = re.sub(r"\s+", " ", query).strip().lower()
        if not query:
            raise WorkspaceError("搜索词不能为空")
        if not isinstance(cursor, int) or cursor < 0:
            raise WorkspaceError("搜索游标无效", {"cursor": cursor})
        terms = [term for term in re.split(r"\s+", query) if term]
        matches: list[tuple[int, HtmlBlock]] = []
        for block in self.blocks:
            source = self._searchable(block)
            score = sum(8 if term in block.text.lower() else 3 if term in source else 0 for term in terms)
            if query in source:
                score += 12
            if query == block.text.lower():
                score += 14
            # Prefer the smallest block that directly contains the requested
            # text over an enclosing section that happens to contain it too.
            score -= min(6, len(block.text) // 120)
            if score:
                matches.append((score, block))
        matches.sort(key=lambda item: (-item[0], item[1].start))
        results = [
            {
                **block.map_item(),
                "score": score,
                "start_line": self._line_for_offset(block.start),
                "end_line": self._line_for_offset(block.end),
            }
            for score, block in matches
        ]
        if cursor >= len(results) and (results or cursor):
            raise WorkspaceError("搜索游标超出范围", {"cursor": cursor, "match_count": len(results)})
        requested = max(1, min(limit, MAX_SEARCH_RESULTS))
        budget = self._result_token_limit(tool_result_max_tokens)

        def payload(items: list[dict], next_cursor: int | None) -> dict:
            remaining = len(results) - (next_cursor if next_cursor is not None else len(results))
            response = {
                "revision": self.revision,
                "query": query,
                "match_count": len(results),
                "cursor": cursor,
                "results": items,
                "next_cursor": next_cursor,
                "remaining_match_count": remaining,
            }
            if next_cursor is not None:
                response.update(
                    {
                        "truncated": True,
                        "omitted_count": remaining,
                        "returned_tokens_limit": budget,
                        "next_step": "请使用相同关键词和 next_cursor 继续读取剩余候选排版块。",
                    }
                )
            return response

        selected: list[dict] = []
        for index, item in enumerate(results[cursor : cursor + requested], start=cursor):
            next_cursor = index + 1 if index + 1 < len(results) else None
            candidate = payload([*selected, item], next_cursor)
            if estimate_tokens(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) <= budget:
                selected.append(item)
                continue
            break
        if results[cursor:] and not selected:
            raise WorkspaceError(
                "单个搜索结果超过当前工具预览预算，未返回不完整条目",
                {
                    "tool_result_max_tokens": budget,
                    "suggestion": "请提高工具预览预算后重试。",
                },
            )
        next_cursor = cursor + len(selected) if cursor + len(selected) < len(results) else None
        return payload(selected, next_cursor)

    def _image_caption(self, node: HtmlNode) -> str:
        """Return the nearest figure caption without treating image URLs as text."""
        ancestor = node.parent
        while ancestor is not None:
            if ancestor.tag == "figure":
                for descendant in self._walk(ancestor.children):
                    if descendant.tag == "figcaption" and descendant.end is not None:
                        caption = _normalise_text(
                            self._redact(self.source_html[descendant.start : descendant.end]),
                            _IMAGE_CONTEXT_TEXT_LIMIT,
                        )
                        if caption:
                            return caption
            ancestor = ancestor.parent
        return ""

    def _image_container(self, node: HtmlNode) -> str:
        """Describe the closest meaningful container using only safe attributes."""
        ancestor = node.parent
        while ancestor is not None:
            if ancestor.tag in {"figure", "section", "article", "aside", "li", "td", "th", "p", "div"}:
                attributes = self._attributes(ancestor)
                return f"{ancestor.tag} {attributes}".strip()[:_IMAGE_CONTEXT_TEXT_LIMIT]
            ancestor = ancestor.parent
        return ""

    def _image_neighbours(self, block: HtmlBlock | None, image_starts: list[int] | None = None) -> tuple[str, str]:
        if block is None:
            return "", ""
        image_starts = image_starts or [node.start for node in self._nodes if node.tag == "img"]
        image_index = image_starts.index(block.start) if block.start in image_starts else -1
        previous_image_start = image_starts[image_index - 1] if image_index > 0 else -1
        next_image_start = image_starts[image_index + 1] if image_index >= 0 and image_index + 1 < len(image_starts) else len(self.source_html)
        candidates = [
            item
            for item in self.blocks
            if item.tag in _IMAGE_CONTEXT_TAGS and item.text and item.start != block.start
        ]
        # A caption after the preceding image belongs to that image, not to
        # the next sibling image. Keep context within the image-to-image gap.
        before = next(
            (
                item.text
                for item in reversed(candidates)
                if item.end <= block.start and item.start > previous_image_start and item.tag != "figcaption"
            ),
            "",
        )
        after = next(
            (item.text for item in candidates if item.start >= block.end and item.start < next_image_start),
            "",
        )
        # In normal article flow the preceding text identifies the following
        # image. Returning a later heading too would make the preceding image
        # look like a second match for that heading.
        if before:
            after = ""
        return before[:_IMAGE_CONTEXT_TEXT_LIMIT], after[:_IMAGE_CONTEXT_TEXT_LIMIT]

    def _image_section(self, block: HtmlBlock | None) -> str:
        if block is None:
            return ""
        if block.heading_path:
            return " > ".join(block.heading_path[-3:])[:_IMAGE_CONTEXT_TEXT_LIMIT]
        for item in reversed(self.blocks):
            if item.start >= block.start or item.tag not in _IMAGE_CONTEXT_TAGS or not item.text:
                continue
            if _SECTION_LABEL_PATTERN.match(item.text.strip()):
                return item.text[:_IMAGE_CONTEXT_TEXT_LIMIT]
        return ""

    @staticmethod
    def _image_location_label(item: dict) -> str:
        parts: list[str] = []
        if item["section"]:
            parts.append(f"章节：{item['section']}")
        if item["caption"]:
            parts.append(f"图注：{item['caption']}")
        if item["alt"]:
            parts.append(f"替代文本：{item['alt']}")
        elif item["title"]:
            parts.append(f"标题属性：{item['title']}")
        if item["before_text"]:
            parts.append(f"前文：{item['before_text']}")
        elif item["after_text"]:
            parts.append(f"后文：{item['after_text']}")
        if not parts and item["container"]:
            parts.append(f"容器：{item['container']}")
        return "；".join(parts)[:(_IMAGE_CONTEXT_TEXT_LIMIT * 2)] or f"图片槽位 {item['slot']}"

    @staticmethod
    def _image_match(item: dict, query: str) -> tuple[int, list[str]]:
        if not query:
            return 0, []
        fields = {
            "替代文本": item["alt"],
            "标题属性": item["title"],
            "无障碍标签": item["aria_label"],
            "图注": item["caption"],
            "所属章节": item["section"],
            "前文": item["before_text"],
            "后文": item["after_text"],
            "容器": item["container"],
        }
        normalized = query.lower()
        terms = [term for term in normalized.split() if term]
        score = 0
        reasons: list[str] = []
        searchable = " ".join(str(value).lower() for value in fields.values() if value)
        if normalized in searchable:
            score += 12
        for term in terms:
            matched = False
            for label, value in fields.items():
                if term and term in str(value).lower():
                    matched = True
                    score += 8 if label in {"替代文本", "标题属性", "无障碍标签", "图注", "所属章节"} else 4
                    if label not in reasons:
                        reasons.append(label)
            if not matched:
                return 0, []
        return score, reasons

    def image_inventory(self, query: str = "", limit: int = 0, cursor: int = 0) -> dict:
        """Return a source-safe, semantically searchable inventory of image slots.

        Image URLs, ``srcset`` values and inline image data are intentionally
        excluded. The result instead describes each image by current-document
        context so a later Agent turn can locate it without stale history.
        ``limit=0`` preserves the legacy full-inventory behaviour; positive
        limits enable paging for large documents.
        """
        query = re.sub(r"\s+", " ", query).strip()
        if not isinstance(cursor, int) or cursor < 0:
            raise WorkspaceError("图片搜索游标无效", {"cursor": cursor})
        if not isinstance(limit, int) or limit < 0:
            raise WorkspaceError("图片搜索数量无效", {"limit": limit})

        blocks_by_start = {block.start: block for block in self.blocks}
        image_starts = [node.start for node in self._nodes if node.tag == "img"]
        images: list[dict] = []
        for node in self._nodes:
            if node.tag != "img":
                continue
            source = node.attrs.get("src", "").strip()
            if not source:
                source_kind = "missing"
                fingerprint = ""
                host = ""
            elif source.lower().startswith("data:"):
                source_kind = "inline_data"
                fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
                host = ""
            else:
                source_kind = "url"
                fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
                host = (urlparse(source).hostname or "").lower()
            block = blocks_by_start.get(node.start)
            before_text, after_text = self._image_neighbours(block, image_starts)
            item = {
                "slot": len(images) + 1,
                "source_kind": source_kind,
                "source_fingerprint": fingerprint,
                "url_host": host,
                "has_srcset": bool(node.attrs.get("srcset", "").strip()),
                "srcset_fingerprint": (
                    hashlib.sha256(node.attrs["srcset"].strip().encode("utf-8")).hexdigest()[:16]
                    if node.attrs.get("srcset", "").strip()
                    else ""
                ),
                "block_id": block.block_id if block else "",
                "path": block.path if block else node.path,
                "alt": re.sub(r"\s+", " ", self._redact(node.attrs.get("alt", ""))).strip()[:_IMAGE_CONTEXT_TEXT_LIMIT],
                "title": re.sub(r"\s+", " ", self._redact(node.attrs.get("title", ""))).strip()[:_IMAGE_CONTEXT_TEXT_LIMIT],
                "aria_label": re.sub(r"\s+", " ", self._redact(node.attrs.get("aria-label", ""))).strip()[:_IMAGE_CONTEXT_TEXT_LIMIT],
                "caption": self._image_caption(node),
                "section": self._image_section(block),
                "container": self._image_container(node),
                "before_text": before_text,
                "after_text": after_text,
            }
            item["location_label"] = self._image_location_label(item)
            images.append(item)
        fingerprints = {item["source_fingerprint"] for item in images if item["source_fingerprint"]}
        matches: list[tuple[int, list[str], dict]] = []
        for item in images:
            score, reasons = self._image_match(item, query)
            if not query or score:
                matches.append((score, reasons, item))
        if query:
            matches.sort(key=lambda value: (-value[0], value[2]["slot"]))
        if cursor >= len(matches) and (matches or cursor):
            raise WorkspaceError("图片搜索游标超出范围", {"cursor": cursor, "match_count": len(matches)})
        requested = len(matches) if limit == 0 else min(max(1, limit), MAX_IMAGE_RESULTS)
        page = matches[cursor : cursor + requested]
        returned = []
        for score, reasons, item in page:
            returned.append({**item, "match_reasons": reasons, "score": score} if query else item)
        next_cursor = cursor + len(returned) if cursor + len(returned) < len(matches) else None
        return {
            "revision": self.revision,
            "image_count": len(images),
            "unique_source_count": len(fingerprints),
            "inline_data_count": sum(item["source_kind"] == "inline_data" for item in images),
            "url_count": sum(item["source_kind"] == "url" for item in images),
            "missing_source_count": sum(item["source_kind"] == "missing" for item in images),
            "query": query,
            "match_count": len(matches),
            "cursor": cursor,
            "images": returned,
            "next_cursor": next_cursor,
            "remaining_image_count": len(matches) - (next_cursor if next_cursor is not None else len(matches)),
        }

    @staticmethod
    def _selection_attrs(attrs: dict[str, str]) -> dict[str, str]:
        stable: dict[str, str] = {}
        for raw_key, raw_value in attrs.items():
            key = raw_key.lower().strip()
            if key not in {"id", "src", "srcset", "href", "name"} and not key.startswith("data-"):
                continue
            value = redact_inline_data_for_identity(str(raw_value)).strip()
            if value:
                stable[key] = value[:2048]
        return stable

    def _node_selection_fingerprint(self, node: HtmlNode) -> dict[str, Any]:
        source = self._redact(self.source_html[node.start : node.end or node.open_end])
        return {
            "tag_name": node.tag,
            "stable_attributes": self._selection_attrs(node.attrs),
            "text": _normalise_text(source, MAX_SELECTED_ELEMENT_TEXT_CHARS),
        }

    @staticmethod
    def _fingerprint_matches(block_fingerprint: dict[str, Any], requested: Mapping[str, Any] | None) -> bool:
        if not isinstance(requested, Mapping):
            return True
        requested_tag = str(requested.get("tag_name", "")).lower().strip()
        if requested_tag and requested_tag != str(block_fingerprint.get("tag_name", "")).lower():
            return False
        requested_attrs = requested.get("stable_attributes")
        current_attrs = block_fingerprint.get("stable_attributes")
        if isinstance(requested_attrs, Mapping):
            if not isinstance(current_attrs, Mapping):
                return False
            for key, value in requested_attrs.items():
                if str(current_attrs.get(str(key).lower(), "")) != str(value):
                    return False
        requested_text = _normalise_text(str(requested.get("text", "")), MAX_SELECTED_ELEMENT_TEXT_CHARS)
        return not requested_text or requested_text == str(block_fingerprint.get("text", ""))

    def _selection_block_for_node(self, node: HtmlNode) -> HtmlBlock | None:
        current: HtmlNode | None = node
        while current is not None:
            block = self._blocks_by_start.get(current.start)
            if block is not None:
                return block
            current = current.parent
        return None

    def _selection_candidates(self, tag_name: str) -> list[tuple[HtmlNode, HtmlBlock]]:
        candidates: list[tuple[HtmlNode, HtmlBlock]] = []
        for node in self._nodes:
            if tag_name and node.tag != tag_name:
                continue
            block = self._selection_block_for_node(node)
            if block is not None:
                candidates.append((node, block))
        return candidates

    @staticmethod
    def _path_candidates(
        candidates: list[tuple[HtmlNode, HtmlBlock]],
        selector: str,
    ) -> list[tuple[HtmlNode, HtmlBlock]]:
        if not selector:
            return []
        return [
            candidate for candidate in candidates
            if candidate[0].path == selector or candidate[0].path.endswith(f" > {selector}")
        ]

    @staticmethod
    def _selection_resolution(
        status: Literal["exact", "relocated", "ambiguous", "missing"],
        candidate: tuple[HtmlNode, HtmlBlock] | None = None,
        reason: str = "",
    ) -> SelectionResolution:
        if candidate is None:
            return SelectionResolution(status, reason=reason)
        node, block = candidate
        return SelectionResolution(
            status,
            block,
            reason,
            target_tag=node.tag,
            target_path=node.path,
            target_text="",
        )

    def resolve_selection(
        self,
        selector: str,
        tag_name: str,
        text: str,
        html: str = "",
        locator: Mapping[str, Any] | None = None,
    ) -> SelectionResolution:
        selector = selector.strip()
        tag_name = tag_name.lower().strip()
        text = _normalise_text(text, 180)
        locator = locator if isinstance(locator, Mapping) else None
        requested_fingerprint = locator.get("fingerprint") if locator else None
        if not isinstance(requested_fingerprint, Mapping):
            requested_fingerprint = None
        candidates = self._selection_candidates(tag_name)
        locator_path = str(locator.get("path", "")).strip() if locator else selector
        if locator and not locator_path:
            parent_path = str(locator.get("parent_path", "")).strip()
            sibling_index = locator.get("sibling_index", 0)
            if parent_path and isinstance(sibling_index, int) and sibling_index > 0 and tag_name:
                locator_path = f"{parent_path} > {tag_name}:nth-of-type({sibling_index})"
        path_candidates = self._path_candidates(candidates, locator_path)
        if path_candidates:
            matching_path = [
                candidate for candidate in path_candidates
                if self._fingerprint_matches(self._node_selection_fingerprint(candidate[0]), requested_fingerprint)
            ]
            if len(matching_path) == 1:
                return self._selection_resolution("exact", matching_path[0])
            if len(path_candidates) == 1 and requested_fingerprint is None:
                return self._selection_resolution("exact", path_candidates[0])

        fingerprint_matches = [
            candidate for candidate in candidates
            if self._fingerprint_matches(self._node_selection_fingerprint(candidate[0]), requested_fingerprint)
        ] if requested_fingerprint else []
        if len(fingerprint_matches) == 1:
            return self._selection_resolution("relocated", fingerprint_matches[0], "路径已变化，已通过元素指纹重新定位")
        if len(fingerprint_matches) > 1:
            return self._selection_resolution("ambiguous", reason="元素指纹匹配到多个当前节点")

        # Backward-compatible clients have no locator. New anchor payloads
        # must not fall through to a weaker legacy match after identity loss.
        if locator:
            return self._selection_resolution("missing", reason="当前文档中未找到该元素的稳定身份")

        # Only accept a unique tag/text candidate; never silently choose the
        # first same-tag node.
        legacy_candidates = candidates
        if text:
            legacy_candidates = [
                candidate for candidate in legacy_candidates
                if text.lower() in self._node_selection_fingerprint(candidate[0])["text"].lower()
            ]
        if html:
            redacted_html = self._redact(html).strip()
            exact_html = [
                candidate for candidate in legacy_candidates
                if self._redact(self.source_html[candidate[0].start : candidate[0].end]).strip() == redacted_html
            ]
            if len(exact_html) == 1:
                return self._selection_resolution("relocated", exact_html[0], "路径已变化，已通过源码重新定位")
            if len(exact_html) > 1:
                return self._selection_resolution("ambiguous", reason="选中源码匹配到多个当前节点")
        if len(legacy_candidates) == 1:
            return self._selection_resolution("relocated", legacy_candidates[0], "路径已变化，已通过标签和文本重新定位")
        if len(legacy_candidates) > 1:
            return self._selection_resolution("ambiguous", reason="标签和文本匹配到多个当前节点")
        return self._selection_resolution("missing", reason="当前文档中未找到该元素")

    def read(
        self,
        block_ids: list[str],
        cursor: int = 0,
        tool_result_max_tokens: int | None = None,
    ) -> dict:
        if not block_ids:
            raise WorkspaceError("请至少提供一个 block_id")
        if len(block_ids) > MAX_READ_BLOCKS:
            raise WorkspaceError(
                f"一次最多读取 {MAX_READ_BLOCKS} 个排版块",
                {
                    "requested_block_count": len(block_ids),
                    "max_read_blocks": MAX_READ_BLOCKS,
                    "suggestion": "请把 block_id 分成多次 read_blocks 调用。",
                },
            )
        if not isinstance(cursor, int) or cursor < 0 or cursor >= len(block_ids):
            raise WorkspaceError(
                "读取游标无效",
                {"cursor": cursor, "requested_block_count": len(block_ids)},
            )

        def payload(items: list[dict], next_cursor: int | None) -> dict:
            remaining = len(block_ids) - (next_cursor if next_cursor is not None else len(block_ids))
            result = {
                "revision": self.revision,
                "requested_block_count": len(block_ids),
                "cursor": cursor,
                "blocks": items,
                "next_cursor": next_cursor,
                "remaining_block_count": remaining,
            }
            if next_cursor is not None:
                result.update(
                    {
                        "truncated": True,
                        "next_step": "请使用相同 block_ids 和 next_cursor 继续读取剩余完整排版块。",
                    }
                )
            return result

        budget = self._result_token_limit(tool_result_max_tokens)
        blocks: list[dict] = []
        for index, block_id in enumerate(block_ids[cursor:], start=cursor):
            block = self._blocks_by_id.get(block_id)
            if not block:
                details: dict[str, str] = {
                    "revision": self.revision,
                    "reason": "block_id_not_current",
                    "suggestion": "请使用目标正文关键词调用 search_html 后再读取；只有需要广泛规划时才调用 get_document_map。",
                }
                if hint := self._stale_block_hints.get(block_id):
                    details["suggested_query"] = hint
                raise WorkspaceError("排版块已变化，请按目标正文关键词调用 search_html 重新定位", details)
            source = self._redact(self.source_html[block.start : block.end])
            candidate = {**block.map_item(), "html": source}
            next_cursor = index + 1 if index + 1 < len(block_ids) else None
            candidate_payload = payload([*blocks, candidate], next_cursor)
            if estimate_tokens(json.dumps(candidate_payload, ensure_ascii=False, separators=(",", ":"))) <= budget:
                blocks.append(candidate)
                continue
            if blocks:
                return payload(blocks, index)
            raise WorkspaceError(
                "单个排版块源码超过当前工具预览预算，未返回不完整 HTML",
                {
                    "estimated_tokens": estimate_tokens(json.dumps(candidate_payload, ensure_ascii=False, separators=(",", ":"))),
                    "tool_result_max_tokens": budget,
                    "block_id": block_id,
                    "suggestion": "请搜索更细粒度的子块后再读取；系统不会返回不完整 HTML。",
                },
            )
        return payload(blocks, None)

    def apply_patch(self, revision: str, operations: list[dict], restore: Callable[[str], str]) -> tuple[str, dict]:
        if revision != self.revision:
            raise WorkspaceError(
                "文档已变化，请先按目标关键词 search_html 后再修改",
                {
                    "expected_revision": revision,
                    "current_revision": self.revision,
                    "reason": "revision_not_current",
                    "suggestion": "局部目标请先 search_html 后 read_blocks；只有需要广泛规划时才调用 get_document_map。",
                },
            )
        if not operations:
            raise WorkspaceError("至少需要一条补丁操作")
        if len(operations) > MAX_PATCH_OPERATIONS:
            raise WorkspaceError(f"一次最多执行 {MAX_PATCH_OPERATIONS} 条补丁操作")

        replacements: list[tuple[int, int, str, HtmlBlock, PatchMode]] = []
        seen_ids: set[str] = set()
        for index, operation in enumerate(operations, start=1):
            block_id = str(operation.get("block_id", ""))
            expected_hash = str(operation.get("expected_hash", ""))
            mode = operation.get("mode")
            block = self._blocks_by_id.get(block_id)
            if not block:
                details: dict[str, str] = {
                    "current_revision": self.revision,
                    "reason": "block_id_not_current",
                    "suggestion": "请使用目标正文关键词调用 search_html 后再读取；只有需要广泛规划时才调用 get_document_map。",
                }
                if hint := self._stale_block_hints.get(block_id):
                    details["suggested_query"] = hint
                raise WorkspaceError(
                    f"第 {index} 条补丁的目标已变化；请先 search_html 重新定位",
                    details,
                )
            if block_id in seen_ids:
                raise WorkspaceError(f"第 {index} 条补丁重复修改同一排版块")
            seen_ids.add(block_id)
            if expected_hash != block.expected_hash:
                raise WorkspaceError(
                    f"第 {index} 条补丁基于旧内容，未写入任何修改",
                    {
                        "block_id": block_id,
                        "current_revision": self.revision,
                        "current_hash": block.expected_hash,
                        # Keep the conflict actionable without returning the
                        # full HTML block. The model can use this locator to
                        # issue a focused read and retry with fresh identity.
                        "current_block": {
                            "block_id": block.block_id,
                            "tag": block.tag,
                            "path": block.path,
                            "text": block.text,
                            "expected_hash": block.expected_hash,
                        },
                        "suggestion": "使用当前 revision 调用 read_blocks 重新读取该排版块后再提交",
                    },
                )
            if mode not in {"replace_outer", "replace_inner", "insert_before", "insert_after", "delete"}:
                raise WorkspaceError(f"第 {index} 条补丁的 mode 无效")
            html_value = operation.get("html", "")
            if mode != "delete" and not isinstance(html_value, str):
                raise WorkspaceError(f"第 {index} 条补丁必须提供 html 字符串")
            if mode == "replace_outer":
                start, end, value = block.start, block.end, restore(str(html_value))
            elif mode == "replace_inner":
                if block.tag in VOID_TAGS:
                    raise WorkspaceError(f"第 {index} 条补丁不能修改 <{block.tag}> 的内部内容")
                start, end, value = block.open_end, block.close_start, restore(str(html_value))
            elif mode == "insert_before":
                start, end, value = block.start, block.start, restore(str(html_value))
            elif mode == "insert_after":
                start, end, value = block.end, block.end, restore(str(html_value))
            else:
                start, end, value = block.start, block.end, ""
            replacements.append((start, end, value, block, mode))

        ordered_ranges = sorted((start, end, block.block_id) for start, end, _, block, _ in replacements)
        for (_, previous_end, _), (next_start, _, _) in zip(ordered_ranges, ordered_ranges[1:]):
            if next_start < previous_end:
                raise WorkspaceError("批量补丁包含嵌套或重叠排版块；请分两次修改以保持原子性")

        next_html = self.source_html
        changed: list[dict] = []
        for start, end, value, block, mode in sorted(replacements, key=lambda item: item[0], reverse=True):
            before = self._redact(self.source_html[start:end])
            next_html = f"{next_html[:start]}{value}{next_html[end:]}"
            changed.append(
                {
                    "block_id": block.block_id,
                    "tag": block.tag,
                    "path": block.path,
                    "mode": mode,
                    "before": _normalise_text(before, 140),
                    "after": _normalise_text(self._redact(value), 140),
                    "character_delta": len(value) - (end - start),
                }
            )
        changed.reverse()
        return next_html, {
            "operation_count": len(changed),
            "blocks": changed,
            "character_delta": sum(item["character_delta"] for item in changed),
            # HtmlEditSession consumes this private range list to preserve
            # same-run IDs after it has validated and accepted the candidate.
            "_identity_ranges": [
                {"start": start, "end": end, "replacement_length": len(value)}
                for start, end, value, _, _ in replacements
            ],
        }
