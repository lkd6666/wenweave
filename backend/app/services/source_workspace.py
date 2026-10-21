"""Virtual files and exact, source-preserving edits for the article agent.

All offsets address the model-visible Unicode string, including inline-data
placeholders. No DOM serialisation or filesystem access occurs in this module.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import cached_property
import hashlib
import json
import re
from typing import Callable

from app.services.html_workspace import WorkspaceError
from app.services.token_budget import estimate_tokens

ARTICLE_PATH = "/article.html"


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str
    revision: str = ""
    readonly: bool = True

    def __post_init__(self) -> None:
        if not self.revision:
            object.__setattr__(self, "revision", hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:20])

    @cached_property
    def line_starts(self) -> list[int]:
        return [0, *(match.end() for match in re.finditer("\n", self.content))]

    def metadata(self) -> dict:
        return {"path": self.path, "revision": self.revision, "readonly": self.readonly,
                "characters": len(self.content), "lines": len(self.line_starts)}


def _fit_content(make_payload: Callable[[int], dict], maximum: int, budget: int) -> dict:
    """Count the actual JSON envelope, not only the source text."""
    def fits(length: int) -> bool:
        return estimate_tokens(json.dumps(make_payload(length), ensure_ascii=False, separators=(",", ":"))) <= budget
    if fits(maximum):
        return make_payload(maximum)
    if not fits(0):
        raise WorkspaceError("工具预算不足以返回文件元数据", {"budget": budget})
    low, high = 0, maximum
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    if maximum and low == 0:
        raise WorkspaceError("工具预算不足以返回源码，请增加预算或缩小请求", {"budget": budget})
    return make_payload(low)


def fit_file_page(entries: list[dict], cursor: int, next_cursor: int | None,
                  budget: int, **metadata) -> dict:
    """Keep directory entries whole, with a cursor for anything omitted."""
    return _fit_content(lambda count: {**metadata, "files": entries[:count],
        "next_cursor": cursor + count if count < len(entries) else next_cursor}, len(entries), budget)


def read_source(file: SourceFile, *, start: int | None = None, end: int | None = None,
                start_line: int | None = None, end_line: int | None = None,
                cursor: int | None = None, budget: int = 4096) -> dict:
    prefer_lines = start is None and end is None
    if (start is not None or end is not None) and (start_line is not None or end_line is not None):
        raise WorkspaceError("行范围与字符范围不能同时指定")
    starts = file.line_starts
    size = len(file.content)
    if start_line is not None or end_line is not None:
        first, last = start_line if start_line is not None else 1, end_line if end_line is not None else len(starts)
        if not 1 <= first <= last <= len(starts):
            raise WorkspaceError("源码行范围无效", {"lines": len(starts)})
        start, end = starts[first - 1], starts[last] if last < len(starts) else size
    start, end = (0 if start is None else start), (size if end is None else end)
    if not 0 <= start <= end <= size:
        raise WorkspaceError("源码字符范围无效", {"characters": size})
    requested_start = start
    if cursor is not None:
        if not start <= cursor <= end:
            raise WorkspaceError("源码续读位置超出请求范围")
        start = cursor

    def payload(length: int) -> dict:
        stop = start + length
        return {**file.metadata(), "start": start, "end": stop,
                "start_line": bisect_right(starts, start),
                "end_line": bisect_right(starts, max(start, stop - 1)),
                "requested_start": requested_start, "requested_end": end,
                "content": file.content[start:stop], "complete": stop == end,
                "next_cursor": stop if stop < end else None}
    result = _fit_content(payload, end - start, budget)
    if prefer_lines and not result["complete"] and "\n" in result["content"]:
        result = payload(result["content"].rfind("\n") + 1)
    return result


def search_source(file: SourceFile, query: str, *, case_sensitive: bool = True,
                  context_chars: int = 120, cursor: int = 0, limit: int = 20,
                  budget: int = 4096) -> dict:
    if not query:
        raise WorkspaceError("源码搜索词不能为空")
    if not 0 <= cursor <= len(file.content) or not 0 <= context_chars <= 2000 or not 1 <= limit <= 100:
        raise WorkspaceError("源码搜索范围或数量无效")
    matcher = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    starts = file.line_starts
    items: list[dict] = []
    next_cursor = None
    for match in matcher.finditer(file.content, cursor):
        item = {"start": match.start(), "end": match.end(),
                "line": bisect_right(starts, match.start()),
                "context_start": max(0, match.start() - context_chars),
                "context_end": min(len(file.content), match.end() + context_chars)}
        item["content"] = file.content[item["context_start"]:item["context_end"]]
        candidate = {**file.metadata(), "query": query, "matches": [*items, item], "match_count": len(items) + 1,
                     "next_cursor": match.end(), "complete": False}
        if len(items) >= limit or estimate_tokens(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) > budget:
            next_cursor = match.start()
            if not items:
                raise WorkspaceError("单个搜索结果超过预算，请减小 context_chars")
            break
        items.append(item)
    result = {**file.metadata(), "query": query, "matches": items, "match_count": len(items),
              "next_cursor": next_cursor, "complete": next_cursor is None}
    if estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > budget:
        raise WorkspaceError("工具预算不足以返回搜索结果，请减少文件数量或上下文范围")
    return result


def search_files_source(files: list[SourceFile], query: str, *, budget: int = 4096, **options) -> dict:
    """Budget the complete multi-file envelope before searching each file."""
    if len(files) == 1:
        return search_source(files[0], query, budget=budget, **options)
    overhead = estimate_tokens('{"files":[]}') + len(files)
    share = (budget - overhead) // len(files)
    if share < 1:
        raise WorkspaceError("多文件搜索超过预算，请减少文件数量")
    result = {"files": [search_source(file, query, budget=share, **options) for file in files]}
    if estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > budget:
        raise WorkspaceError("多文件搜索超过预算，请减少文件数量或上下文范围")
    return result


def apply_replacements(content: str, edits: list[dict]) -> tuple[str, dict]:
    if not edits:
        raise WorkspaceError("至少需要一条源码修改")
    ranges: list[tuple[int, int, str]] = []
    for index, edit in enumerate(edits, 1):
        if not isinstance(edit, dict) or not isinstance(edit.get("old_text"), str) or not isinstance(edit.get("new_text"), str):
            raise WorkspaceError(f"第 {index} 条修改必须提供 old_text 和 new_text 字符串")
        old, new = edit["old_text"], edit["new_text"]
        start, end = edit.get("start", 0), edit.get("end", len(content))
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= len(content):
            raise WorkspaceError(f"第 {index} 条源码范围无效")
        if not isinstance(edit.get("replace_all", False), bool):
            raise WorkspaceError("replace_all 必须是布尔值")
        if not old:
            if start != end or "start" not in edit:
                raise WorkspaceError("插入操作必须指定相同的 start 和 end")
            matches = [(start, end)]
        else:
            matches = [(start + m.start(), start + m.end()) for m in re.finditer(re.escape(old), content[start:end])]
        if not matches or (len(matches) != 1 and not edit.get("replace_all", False)):
            raise WorkspaceError(f"第 {index} 条原文匹配数量为 {len(matches)}，未写入任何修改",
                                 {"edit": index, "match_count": len(matches), "locations": matches[:8],
                                  "suggestion": "重新搜索源码，缩小 start/end 范围或明确使用 replace_all。"})
        ranges.extend((left, right, new) for left, right in matches)
    return splice_source(content, ranges)


def splice_source(content: str, ranges: list[tuple[int, int, str]]) -> tuple[str, dict]:
    ordered = sorted(ranges, key=lambda item: (item[0], item[1]))
    for previous, following in zip(ordered, ordered[1:]):
        if following[0] < previous[1] or following[0] == previous[0]:
            raise WorkspaceError("源码修改范围重叠，未写入任何修改", {"conflicts": [
                {"start": item[0], "end": item[1]} for item in (previous, following)]})
    pieces: list[str] = []
    position = 0
    delta = 0
    changes = []
    for start, end, value in ordered:
        pieces.extend((content[position:start], value))
        position = end
        changes.append({"start": start + delta, "end": start + delta + len(value),
                        "before_start": start, "before_end": end, "before": content[start:end][:140],
                        "after": value[:140], "character_delta": len(value) - (end - start)})
        delta += len(value) - (end - start)
    pieces.append(content[position:])
    return "".join(pieces), {"operation_count": len(changes), "changes": changes,
                              "character_delta": sum(item["character_delta"] for item in changes)}


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")


def apply_unified_diff(content: str, patch: str, path: str = ARTICLE_PATH) -> tuple[str, dict]:
    """Strict single-file unified diff, including CRLF and missing final LF."""
    lines = [line.removesuffix("\r") for line in patch.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        raise WorkspaceError("请提供含 ---、+++ 文件头和 @@ hunk 的 unified diff")
    for header in lines[:2]:
        name = header[4:].split("\t", 1)[0]
        if name.startswith(("a/", "b/")):
            name = "/" + name[2:]
        if name != path:
            raise WorkspaceError("补丁文件头与目标文件不一致", {"path": path})
    source_lines = re.findall(r"[^\n]*\n|[^\n]+$", content)
    offsets = [0]
    for line in source_lines:
        offsets.append(offsets[-1] + len(line))
    newline = "\r\n" if "\r\n" in content else "\n"
    ranges = []
    index = 2
    delta = 0
    last_end = 0
    while index < len(lines):
        header = _HUNK.fullmatch(lines[index])
        if not header:
            raise WorkspaceError("无效的 unified diff hunk", {"patch_line": index + 1})
        old_line, old_count, new_line, new_count = (int(value) if value is not None else 1 for value in header.groups())
        begin = old_line - 1 if old_count else old_line
        new_begin = new_line - 1 if new_count else new_line
        if begin < last_end or begin < 0 or begin + old_count > len(source_lines) or new_begin != begin + delta:
            raise WorkspaceError("补丁行范围无效或重叠")
        old_entries: list[tuple[str, bool]] = []
        new_entries: list[tuple[str, bool, str]] = []
        new_context_indices: list[int | None] = []
        previous_kind = ""
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line == "\\ No newline at end of file":
                if not previous_kind:
                    raise WorkspaceError("无效的文件末尾换行标记")
                if previous_kind in {" ", "-"}:
                    old_entries[-1] = (old_entries[-1][0], False)
                if previous_kind in {" ", "+"}:
                    text, _, kind = new_entries[-1]
                    new_entries[-1] = (text, False, kind)
                previous_kind = ""
            elif line and line[0] in {" ", "+", "-"}:
                previous_kind = line[0]
                if previous_kind in {" ", "-"}:
                    old_entries.append((line[1:], True))
                if previous_kind in {" ", "+"}:
                    new_entries.append((line[1:], True, previous_kind))
                    new_context_indices.append(len(old_entries) - 1 if previous_kind == " " else None)
            else:
                raise WorkspaceError("无效的补丁正文", {"patch_line": index + 1})
            index += 1
        if len(old_entries) != old_count or len(new_entries) != new_count:
            raise WorkspaceError("补丁 hunk 行数与文件头不一致")
        originals = source_lines[begin:begin + old_count]
        for line_index, (original, (expected, has_newline)) in enumerate(zip(originals, old_entries)):
            ending = "\r\n" if original.endswith("\r\n") else "\n" if original.endswith("\n") else ""
            actual = original[:-len(ending)] if ending else original
            if actual != expected or bool(ending) != has_newline:
                raise WorkspaceError("补丁原文或上下文不匹配，未写入任何修改", {"line": begin + line_index + 1,
                    "start": offsets[begin + line_index], "end": offsets[begin + line_index + 1]})
        replacement = []
        # Replay context from the original file to retain even mixed EOLs.
        for (text, has_newline, kind), context_index in zip(new_entries, new_context_indices):
            if kind == " ":
                assert context_index is not None
                replacement.append(originals[context_index])
            else:
                replacement.append(text + (newline if has_newline else ""))
        ranges.append((offsets[begin], offsets[begin + old_count], "".join(replacement)))
        last_end = begin + old_count
        delta += new_count - old_count
    if not ranges:
        raise WorkspaceError("补丁没有修改内容")
    return splice_source(content, ranges)


class SourceWorkspace:
    """An allowlisted virtual namespace, with lazy current and history files."""

    def __init__(self, article: Callable[[], SourceFile]):
        self._files: dict[str, Callable[[], SourceFile]] = {ARTICLE_PATH: article}
        self.history_loader: Callable[[int], SourceFile] | None = None

    def register(self, file: SourceFile) -> None:
        self._files[file.path] = lambda: file

    def get(self, path: str) -> SourceFile:
        if path in self._files:
            return self._files[path]()
        match = re.fullmatch(r"/history/(\d+)\.html", path)
        if match and self.history_loader:
            return self.history_loader(int(match[1]))
        raise WorkspaceError("文件不在当前授权工作区中", {"path": path})

    def list_files(self) -> list[dict]:
        return [self.get(path).metadata() for path in self._files]

    @property
    def revision(self) -> str:
        return self.get(ARTICLE_PATH).revision

    def map_payload(self, *args, **kwargs) -> dict:
        return {"revision": self.revision, "tool_protocol": "v2", "files": self.list_files(), "blocks": [], "block_count": 0}
