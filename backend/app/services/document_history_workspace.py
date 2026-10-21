"""Read-only historical HTML workspaces for the editing Agent."""
from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.document_version import DocumentVersion
from app.services.document_versions import DocumentVersionStorageError, materialize_document_version
from app.services.html_workspace import HtmlWorkspace, WorkspaceError
from app.services.selected_elements import redact_inline_data
from app.services.token_budget import estimate_tokens

HISTORY_VERSION_PAGE_SIZE = 20
HISTORY_SEARCH_PAGE_SIZE = 8
HISTORY_COMPARE_PAGE_SIZE = 8
HISTORY_WORKSPACE_CACHE_MAX_ENTRIES = 2
HISTORY_WORKSPACE_CACHE_MAX_SOURCE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class _HistoryWorkspaceCacheEntry:
    workspace: HtmlWorkspace
    source_bytes: int


class _HistoryWorkspaceCache:
    """A bounded, run-local cache for immutable historical version indexes."""

    def __init__(
        self,
        *,
        max_entries: int = HISTORY_WORKSPACE_CACHE_MAX_ENTRIES,
        max_source_bytes: int = HISTORY_WORKSPACE_CACHE_MAX_SOURCE_BYTES,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.max_source_bytes = max(1, int(max_source_bytes))
        self._entries: OrderedDict[int, _HistoryWorkspaceCacheEntry] = OrderedDict()
        self._source_bytes = 0
        self._hits = 0
        self._misses = 0
        self._skipped_oversize = 0
        self._evictions = 0
        self._lock = threading.RLock()

    def get(self, version_id: int) -> HtmlWorkspace | None:
        with self._lock:
            entry = self._entries.pop(version_id, None)
            if entry is None:
                self._misses += 1
                return None
            self._entries[version_id] = entry
            self._hits += 1
            return entry.workspace

    def put(self, version_id: int, workspace: HtmlWorkspace, source_bytes: int) -> None:
        if source_bytes > self.max_source_bytes:
            with self._lock:
                self._skipped_oversize += 1
            return
        with self._lock:
            previous = self._entries.pop(version_id, None)
            if previous is not None:
                self._source_bytes -= previous.source_bytes
            while self._entries and (
                len(self._entries) >= self.max_entries or self._source_bytes + source_bytes > self.max_source_bytes
            ):
                _, evicted = self._entries.popitem(last=False)
                self._source_bytes -= evicted.source_bytes
                self._evictions += 1
            self._entries[version_id] = _HistoryWorkspaceCacheEntry(workspace, source_bytes)
            self._source_bytes += source_bytes

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "skipped_oversize": self._skipped_oversize,
                "evictions": self._evictions,
                "entries": len(self._entries),
                "source_bytes": self._source_bytes,
            }


def _is_retryable_db_disconnect(exc: DBAPIError) -> bool:
    """Return whether a read can safely be retried on a new DB connection."""
    if exc.connection_invalidated:
        return True
    detail = str(exc).lower()
    return any(
        marker in detail
        for marker in (
            "lost connection",
            "server has gone away",
            "connection reset",
            "connection aborted",
            "winerror 10053",
            "2006",
            "2013",
            "2055",
        )
    )


def _with_isolated_read_session(method: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Run an Agent history read in a fresh session, retrying one disconnect."""

    @wraps(method)
    def wrapped(self: "DocumentHistoryWorkspace", *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self._session_factory is None:
            return method(self, *args, **kwargs)

        # ToolNode can schedule several read tools at once. Keep the existing
        # per-workspace ordering while each operation gets a short-lived socket.
        with self._db_lock:
            for attempt in range(2):
                db = self._session_factory()
                try:
                    isolated = DocumentHistoryWorkspace(
                        db,
                        self.document_id,
                        self.tool_result_max_tokens,
                        workspace_cache=self._workspace_cache,
                    )
                    return method(isolated, *args, **kwargs)
                except DBAPIError as exc:
                    try:
                        db.rollback()
                    except DBAPIError:
                        pass
                    if attempt == 0 and _is_retryable_db_disconnect(exc):
                        continue
                    if _is_retryable_db_disconnect(exc):
                        raise WorkspaceError(
                            "历史版本数据库连接暂时中断，请重试本次读取",
                            {"retryable": True},
                        ) from exc
                    raise
                finally:
                    db.close()

        raise AssertionError("history read retry loop exited unexpectedly")

    return wrapped


def _excerpt(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else f"{value[: max(0, limit - 1)]}…"


class DocumentHistoryWorkspace:
    """Expose immutable document versions as read-only, redacted HTML workspaces."""

    def __init__(
        self,
        db: Session,
        document_id: int,
        tool_result_max_tokens: int,
        session_factory: Callable[[], Session] | None = None,
        workspace_cache: _HistoryWorkspaceCache | None = None,
    ):
        self.db = db
        self.document_id = document_id
        self.tool_result_max_tokens = max(1, int(tool_result_max_tokens))
        self._session_factory = session_factory
        self._workspace_cache = workspace_cache or _HistoryWorkspaceCache()
        # LangGraph 的 ToolNode 会把同一条助手消息里的只读工具放到多个
        # 线程执行，但一个 SQLAlchemy Session / PyMySQL 连接不能并发读写。
        # 历史版本操作均为只读，按此锁串行化可避免 MySQL 数据包交错。
        self._db_lock = threading.RLock()

    def set_tool_result_limit(self, limit: int) -> None:
        """Apply the active per-tool preview budget before a ToolNode batch."""
        with self._db_lock:
            self.tool_result_max_tokens = max(1, int(limit))

    def cache_metrics(self) -> dict[str, int]:
        return self._workspace_cache.metrics()

    def _workspace_budget(self) -> int:
        # Version metadata and the read-only marker wrap the workspace result.
        return max(1, self.tool_result_max_tokens - 180)

    @staticmethod
    def _version_metadata(version: DocumentVersion) -> dict[str, Any]:
        return {
            "version_id": version.id,
            "version_number": version.version_number,
            "title": _excerpt(version.title, 96),
            "source": version.source.value if hasattr(version.source, "value") else str(version.source),
            "label": _excerpt(version.label, 120),
            "created_at": version.created_at.isoformat() if version.created_at else "",
        }

    def _page_versions(self, cursor: int, limit: int) -> tuple[list[DocumentVersion], int, int]:
        if not isinstance(cursor, int) or cursor < 0:
            raise WorkspaceError("历史版本游标无效", {"cursor": cursor})
        if not isinstance(limit, int) or limit < 1:
            raise WorkspaceError("历史版本分页大小无效", {"limit": limit})
        page_size = min(limit, HISTORY_VERSION_PAGE_SIZE)
        total = int(
            self.db.query(func.count(DocumentVersion.id))
            .filter(DocumentVersion.document_id == self.document_id)
            .scalar()
            or 0
        )
        if cursor >= total and total:
            raise WorkspaceError("历史版本游标超出范围", {"cursor": cursor, "total_versions": total})
        versions = (
            self.db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == self.document_id)
            .order_by(desc(DocumentVersion.version_number))
            .offset(cursor)
            .limit(page_size)
            .all()
        )
        return versions, total, page_size

    def _version(self, version_id: int) -> DocumentVersion:
        version = (
            self.db.query(DocumentVersion)
            .filter(DocumentVersion.id == version_id, DocumentVersion.document_id == self.document_id)
            .first()
        )
        if not version:
            raise WorkspaceError("历史版本不存在", {"version_id": version_id})
        return version

    def _workspace(self, version_id: int) -> tuple[DocumentVersion, HtmlWorkspace]:
        version = self._version(version_id)
        cached = self._workspace_cache.get(version.id)
        if cached is not None:
            return version, cached
        try:
            html = materialize_document_version(self.db, version)
        except DocumentVersionStorageError as exc:
            raise WorkspaceError("历史版本内容无法读取", {"version_id": version_id}) from exc
        workspace = HtmlWorkspace(
            html,
            redact=redact_inline_data,
            tool_result_max_tokens=self._workspace_budget(),
        )
        self._workspace_cache.put(version.id, workspace, len(html.encode("utf-8")))
        return version, workspace

    def _fit_page_entries(
        self,
        *,
        key: str,
        entries: list[dict[str, Any]],
        payload: dict[str, Any],
        cursor: int,
        total: int,
        remaining_key: str,
    ) -> dict[str, Any]:
        """Return only complete directory/diff entries that fit this turn.

        Raw tool-output retention is a fallback for arbitrary JSON. Version
        listings and comparisons have native cursors, so preserve their
        structured paging semantics instead of returning a head/tail preview
        that loses the middle of a list.
        """
        selected: list[dict[str, Any]] = []
        for entry in entries:
            next_offset = cursor + len(selected) + 1
            candidate = {
                **payload,
                key: [*selected, entry],
                "next_cursor": next_offset if next_offset < total else None,
                remaining_key: max(0, total - next_offset),
            }
            if estimate_tokens(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) > self.tool_result_max_tokens:
                break
            selected.append(entry)
        if entries and not selected:
            raise WorkspaceError(
                "单个历史条目超过当前工具预览预算，未返回不完整条目",
                {
                    "tool_result_max_tokens": self.tool_result_max_tokens,
                    "suggestion": "请在下一轮使用更大的上下文预算后重试。",
                },
            )
        next_cursor = cursor + len(selected)
        return {
            **payload,
            key: selected,
            "next_cursor": next_cursor if next_cursor < total else None,
            remaining_key: max(0, total - next_cursor),
        }

    @_with_isolated_read_session
    def source_file(self, version_id: int) -> dict[str, Any]:
        """Materialize a permitted history file without building a DOM index."""
        with self._db_lock:
            version = self._version(version_id)
            try:
                source = materialize_document_version(self.db, version)
            except DocumentVersionStorageError as exc:
                raise WorkspaceError("历史版本内容无法读取", {"version_id": version_id}) from exc
            return {"content": source, "version": self._version_metadata(version)}

    @_with_isolated_read_session
    def list_versions(self, cursor: int = 0, limit: int = HISTORY_VERSION_PAGE_SIZE) -> dict[str, Any]:
        with self._db_lock:
            versions, total, page_size = self._page_versions(cursor, limit)
            return self._fit_page_entries(
                key="versions",
                entries=[self._version_metadata(version) for version in versions],
                payload={
                "total_versions": total,
                "cursor": cursor,
                "page_size": page_size,
                },
                cursor=cursor,
                total=total,
                remaining_key="remaining_version_count",
            )

    @_with_isolated_read_session
    def search_versions(self, query: str, cursor: int = 0, limit: int = HISTORY_SEARCH_PAGE_SIZE) -> dict[str, Any]:
        with self._db_lock:
            query = query.strip()
            if not query:
                raise WorkspaceError("历史版本搜索关键词不能为空")
            versions, total, page_size = self._page_versions(cursor, min(limit, HISTORY_SEARCH_PAGE_SIZE))
            matches: list[dict[str, Any]] = []
            scanned = 0
            for version in versions:
                _, workspace = self._workspace(version.id)
                result = workspace.search(query, limit=1, tool_result_max_tokens=self._workspace_budget())
                items = result.get("results", []) if isinstance(result, dict) else []
                entry: dict[str, Any] | None = None
                if items:
                    item = items[0]
                    entry = {
                        "version": self._version_metadata(version),
                        "match_count": result.get("match_count", 1),
                        "block": {
                            "block_id": item.get("block_id", ""),
                            "tag": item.get("tag", ""),
                            "path": item.get("path", ""),
                            "text": _excerpt(str(item.get("text", ""))),
                        },
                    }
                next_offset = cursor + scanned + 1
                candidate = {
                    "query": query,
                    "total_versions": total,
                    "cursor": cursor,
                    "scanned_version_count": scanned + 1,
                    "page_size": page_size,
                    "matches": [*matches, *([entry] if entry else [])],
                    "next_cursor": next_offset if next_offset < total else None,
                    "remaining_version_count": max(0, total - next_offset),
                }
                if estimate_tokens(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) > self.tool_result_max_tokens:
                    if scanned == 0:
                        raise WorkspaceError(
                            "单个历史搜索条目超过当前工具预览预算，未返回不完整条目",
                            {
                                "tool_result_max_tokens": self.tool_result_max_tokens,
                                "suggestion": "请在下一轮使用更大的上下文预算后重试。",
                            },
                        )
                    break
                if entry:
                    matches.append(entry)
                scanned += 1
            next_cursor = cursor + scanned
            return {
                "query": query,
                "total_versions": total,
                "cursor": cursor,
                "scanned_version_count": scanned,
                "page_size": page_size,
                "matches": matches,
                "next_cursor": next_cursor if next_cursor < total else None,
                "remaining_version_count": max(0, total - next_cursor),
            }

    @_with_isolated_read_session
    def search_version(self, version_id: int, query: str, limit: int = 8) -> dict[str, Any]:
        """Search all matching blocks inside one selected historical version.

        ``search_versions`` is a version-directory tool and deliberately
        returns one representative match per version.  This method is the
        inspection tool for a selected version, including every requested
        image block when the limit permits.
        """
        with self._db_lock:
            query = query.strip()
            if not query:
                raise WorkspaceError("历史版本搜索关键词不能为空")
            version, workspace = self._workspace(version_id)
            return {
                "version": self._version_metadata(version),
                **workspace.search(query, limit, tool_result_max_tokens=self._workspace_budget()),
                "read_only": True,
            }

    @_with_isolated_read_session
    def image_inventory(self, version_id: int) -> dict[str, Any]:
        """Inspect image-slot identity without exposing source URLs or data."""
        with self._db_lock:
            version, workspace = self._workspace(version_id)
            return {
                "version": self._version_metadata(version),
                **workspace.image_inventory(),
                "read_only": True,
            }

    @_with_isolated_read_session
    def read_blocks(self, version_id: int, block_ids: list[str], cursor: int | str = 0) -> dict[str, Any]:
        with self._db_lock:
            version, workspace = self._workspace(version_id)
            return {
                "version": self._version_metadata(version),
                **workspace.read(block_ids, cursor, tool_result_max_tokens=self._workspace_budget()),
                "read_only": True,
            }

    @_with_isolated_read_session
    def compare_version(
        self,
        version_id: int,
        current_workspace: HtmlWorkspace,
        cursor: int = 0,
        limit: int = HISTORY_COMPARE_PAGE_SIZE,
    ) -> dict[str, Any]:
        with self._db_lock:
            if not isinstance(cursor, int) or cursor < 0:
                raise WorkspaceError("历史对比游标无效", {"cursor": cursor})
            if not isinstance(limit, int) or limit < 1:
                raise WorkspaceError("历史对比分页大小无效", {"limit": limit})
            version, historical_workspace = self._workspace(version_id)
            # Include container blocks as well as leaves. A paragraph containing
            # an image is still the meaningful unit for detecting rewritten text.
            historical = {block.path: block for block in historical_workspace.blocks}
            current = {block.path: block for block in current_workspace.blocks}
            ordered_paths = [*current]
            ordered_paths.extend(path for path in historical if path not in current)
            changes: list[dict[str, Any]] = []
            for path in ordered_paths:
                old = historical.get(path)
                now = current.get(path)
                if old and now and old.expected_hash == now.expected_hash:
                    continue
                changes.append(
                    {
                        "path": path,
                        "tag": (now or old).tag if now or old else "",
                        "status": "added" if old is None else "removed" if now is None else "changed",
                        "historical_text": _excerpt(old.text) if old else "",
                        "current_text": _excerpt(now.text) if now else "",
                        "historical_block_id": old.block_id if old else "",
                        "current_block_id": now.block_id if now else "",
                    }
                )
            if cursor >= len(changes) and changes:
                raise WorkspaceError("历史对比游标超出范围", {"cursor": cursor, "total_changed_blocks": len(changes)})
            page_size = min(limit, HISTORY_COMPARE_PAGE_SIZE)
            return self._fit_page_entries(
                key="changes",
                entries=changes[cursor : cursor + page_size],
                payload={
                "version": self._version_metadata(version),
                "historical_revision": historical_workspace.revision,
                "current_revision": current_workspace.revision,
                "total_changed_blocks": len(changes),
                "cursor": cursor,
                "read_only": True,
                },
                cursor=cursor,
                total=len(changes),
                remaining_key="remaining_changed_block_count",
            )
