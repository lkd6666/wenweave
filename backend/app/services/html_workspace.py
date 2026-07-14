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
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Iterable, Literal

from app.services.token_budget import estimate_tokens

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
MAX_READ_BLOCKS = 4
DEFAULT_TOOL_RESULT_MAX_TOKENS = 4_096

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
    close_start: int | None = None
    end: int | None = None
    children: list["HtmlNode"] = field(default_factory=list)

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


class _SourceParser(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = self._line_offsets(source)
        self.roots: list[HtmlNode] = []
        self.stack: list[HtmlNode] = []

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
        start = self.source_offset()
        raw = self.get_starttag_text() or ""
        node = HtmlNode(
            tag=tag.lower(),
            start=start,
            open_end=start + len(raw),
            parent=self.stack[-1] if self.stack else None,
            attrs={key.lower(): value or "" for key, value in attrs},
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
    ):
        self.source_html = source_html
        self._redact = redact or (lambda value: value)
        self.tool_result_max_tokens = max(1, int(tool_result_max_tokens))
        self.safe_html = self._redact(source_html)
        self.revision = _safe_hash(self.safe_html)
        parser = _SourceParser(source_html)
        parser.feed(source_html)
        parser.close()
        parser.close_open_nodes()
        self._line_offsets = parser.line_offsets
        self._nodes = list(self._walk(parser.roots))
        self.blocks = self._build_blocks()
        self._blocks_by_id = {block.block_id: block for block in self.blocks}

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

    def _path(self, node: HtmlNode) -> str:
        parts: list[str] = []
        current: HtmlNode | None = node
        while current is not None:
            siblings = current.parent.children if current.parent else [item for item in self._nodes if item.parent is None]
            same_tag = [item for item in siblings if item.tag == current.tag]
            index = same_tag.index(current) + 1 if current in same_tag else 1
            parts.append(f"{current.tag}:nth-of-type({index})")
            current = current.parent
        return " > ".join(reversed(parts))

    def _attributes(self, node: HtmlNode) -> str:
        values: list[str] = []
        for key in ("id", "class", "data-role", "role", "style"):
            value = node.attrs.get(key, "").strip()
            if not value:
                continue
            if key == "style":
                value = re.sub(r"\s+", " ", value)[:120]
            values.append(f'{key}="{value}"')
        return " ".join(values)[:260]

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
            block_id = f"b-{self.revision[:8]}-{node.start:x}-{node.tag}"
            blocks.append(
                HtmlBlock(
                    block_id=block_id,
                    tag=node.tag,
                    start=node.start,
                    open_end=node.open_end,
                    close_start=node.close_start,
                    end=node.end,
                    path=self._path(node),
                    heading_path=tuple(heading_stack),
                    text=text,
                    attributes=self._attributes(node),
                    has_image="<img" in safe.lower(),
                    has_table="<table" in safe.lower(),
                    expected_hash=_safe_hash(safe),
                )
            )
        return blocks

    def _fit_index_items(
        self,
        *,
        kind: str,
        items: list[dict],
        payload: dict,
        requested_count: int,
    ) -> dict:
        """Shrink directory/search lists at whole-item boundaries.

        Unlike source reads, index rows can safely be omitted.  The response
        tells the model what happened so it can issue a narrower search.
        """
        selected: list[dict] = []
        for item in items[:requested_count]:
            candidate = {**payload, kind: [*selected, item]}
            if estimate_tokens(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) > self.tool_result_max_tokens:
                break
            selected.append(item)
        omitted = max(0, len(items) - len(selected))
        if omitted:
            metadata = {
                "truncated": True,
                "omitted_count": omitted,
                "returned_tokens_limit": self.tool_result_max_tokens,
                "next_step": "请使用更具体的关键词搜索，或分批读取候选排版块。",
            }
            # The truncation metadata itself costs tokens. Remove full rows
            # until the final JSON (not merely its pre-metadata form) fits.
            while selected:
                result = {**payload, kind: selected, **metadata}
                if estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= self.tool_result_max_tokens:
                    break
                selected.pop()
                metadata["omitted_count"] = len(items) - len(selected)
            result = {**payload, kind: selected, **metadata}
        else:
            result = {**payload, kind: selected}
        return result

    def map_payload(self, limit: int = MAX_MAP_BLOCKS) -> dict:
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
        )

    def _searchable(self, block: HtmlBlock) -> str:
        return " ".join((block.tag, block.path, block.attributes, " ".join(block.heading_path), block.text)).lower()

    def search(self, query: str, limit: int = 8) -> dict:
        query = re.sub(r"\s+", " ", query).strip().lower()
        if not query:
            raise WorkspaceError("搜索词不能为空")
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
        return self._fit_index_items(
            kind="results",
            items=results,
            payload={"revision": self.revision, "query": query, "match_count": len(matches)},
            requested_count=max(1, min(limit, MAX_SEARCH_RESULTS)),
        )

    def resolve_selection(self, selector: str, tag_name: str, text: str) -> HtmlBlock | None:
        selector = selector.strip()
        tag_name = tag_name.lower().strip()
        text = _normalise_text(text, 180)
        exact = next((block for block in self.blocks if selector and block.path.endswith(selector)), None)
        if exact:
            return exact
        candidates = [block for block in self.blocks if block.tag == tag_name] or self.blocks
        if text:
            text_lower = text.lower()
            candidates = [block for block in candidates if text_lower in block.text.lower()] or candidates
        return min(candidates, key=lambda block: block.start, default=None)

    def read(self, block_ids: list[str]) -> dict:
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
        blocks: list[dict] = []
        for block_id in block_ids:
            block = self._blocks_by_id.get(block_id)
            if not block:
                raise WorkspaceError("排版块已变化，请先调用 get_document_map 或 search_html 重新定位", {"revision": self.revision})
            source = self._redact(self.source_html[block.start : block.end])
            blocks.append({**block.map_item(), "html": source})
        result = {"revision": self.revision, "blocks": blocks}
        estimated_tokens = estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        if estimated_tokens > self.tool_result_max_tokens:
            raise WorkspaceError(
                "读取源码超过该模型的单次工具返回上限，未返回不完整 HTML",
                {
                    "estimated_tokens": estimated_tokens,
                    "tool_result_max_tokens": self.tool_result_max_tokens,
                    "requested_blocks": len(block_ids),
                    "suggestion": "请先搜索更细粒度的子块，或每次只读取一个较小的排版块。",
                },
            )
        return result

    def apply_patch(self, revision: str, operations: list[dict], restore: Callable[[str], str]) -> tuple[str, dict]:
        if revision != self.revision:
            raise WorkspaceError(
                "文档已变化，请重新获取文档地图后再修改",
                {"expected_revision": revision, "current_revision": self.revision},
            )
        if not operations:
            raise WorkspaceError("至少需要一条补丁操作")
        if len(operations) > 12:
            raise WorkspaceError("一次最多执行 12 条补丁操作")

        replacements: list[tuple[int, int, str, HtmlBlock, PatchMode]] = []
        seen_ids: set[str] = set()
        for index, operation in enumerate(operations, start=1):
            block_id = str(operation.get("block_id", ""))
            expected_hash = str(operation.get("expected_hash", ""))
            mode = operation.get("mode")
            block = self._blocks_by_id.get(block_id)
            if not block:
                raise WorkspaceError(
                    f"第 {index} 条补丁的目标已变化；请先 search_html 或 get_document_map 重新定位",
                    {"current_revision": self.revision},
                )
            if block_id in seen_ids:
                raise WorkspaceError(f"第 {index} 条补丁重复修改同一排版块")
            seen_ids.add(block_id)
            if expected_hash != block.expected_hash:
                raise WorkspaceError(
                    f"第 {index} 条补丁基于旧内容，未写入任何修改",
                    {"block_id": block_id, "current_hash": block.expected_hash, "suggestion": "重新读取该排版块后再提交"},
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
        return next_html, {"operation_count": len(changed), "blocks": changed, "character_delta": sum(item["character_delta"] for item in changed)}
