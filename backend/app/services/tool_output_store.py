"""OpenCode-style durable storage for oversized provider-visible tool results."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.chat_tool_output import ChatToolOutput
from app.services.token_budget import estimate_tokens


OUTPUT_ID_PREFIX = "toolout-"
MIN_PREVIEW_TOKENS = 256
PREVIEW_METADATA_RESERVE_TOKENS = 320


class ToolOutputError(ValueError):
    """A recoverable error that should be returned to the Agent as a tool result."""


@dataclass(frozen=True)
class ToolOutputBinding:
    content: str
    output_id: str | None = None
    stored: bool = False
    original_tokens: int = 0
    original_bytes: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(value: datetime, now: datetime | None = None) -> bool:
    # SQLite returns naive values for DateTime(timezone=True), while MySQL
    # deployments return timezone-aware values. Treat a naive DB timestamp as
    # UTC because every expiry is written from ``_now`` above.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= (now or _now())


def _line_count(value: str) -> int:
    return 0 if not value else value.count("\n") + 1


def _take_prefix(value: str, max_tokens: int) -> str:
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
    return value[:low]


def _take_suffix(value: str, max_tokens: int) -> str:
    if max_tokens <= 0 or not value:
        return ""
    if estimate_tokens(value) <= max_tokens:
        return value
    low, high = 0, len(value)
    while low < high:
        # Find the first offset whose suffix fits. ``high`` is always a
        # fitting candidate, so this branch must strictly reduce the interval.
        middle = (low + high) // 2
        if estimate_tokens(value[middle:]) <= max_tokens:
            high = middle
        else:
            low = middle + 1
    return value[low:]


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": max(0, int(offset))}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        offset = value.get("offset")
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ToolOutputError("工具结果游标无效，请从原始 output_id 重新读取") from exc
    if not isinstance(offset, int) or offset < 0:
        raise ToolOutputError("工具结果游标无效，请从原始 output_id 重新读取")
    return offset


class ToolOutputStore:
    """Store complete oversized values while returning a bounded model preview."""

    def __init__(
        self,
        *,
        document_id: int,
        session_id: int,
        run_id: str,
        retention_days: int | None = None,
        storage_max_bytes: int | None = None,
    ):
        settings = get_settings()
        self.document_id = document_id
        self.session_id = session_id
        self.run_id = run_id
        # Complete tool values are bounded by a configured TTL.  The optional
        # value is useful for tests and explicit shorter-lived artifacts.
        self.retention_days = max(1, int(retention_days or settings.CHAT_TOOL_OUTPUT_RETENTION_DAYS))
        self.storage_max_bytes = max(1, int(storage_max_bytes or settings.CHAT_TOOL_OUTPUT_MAX_BYTES))

    def bind(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        content: str,
        max_preview_tokens: int,
        force_store: bool = False,
    ) -> ToolOutputBinding:
        """Persist an oversized result and return provider-safe content.

        This method intentionally owns a short-lived Session. ToolNode executes
        sibling tools concurrently, so using the request's shared Session here
        would make a successful multi-tool call race its own audit writes.
        """
        content = content if isinstance(content, str) else str(content)
        original_tokens = estimate_tokens(content)
        original_bytes = len(content.encode("utf-8"))
        preview_limit = max(MIN_PREVIEW_TOKENS, int(max_preview_tokens))
        if original_tokens <= preview_limit and not force_store:
            return ToolOutputBinding(content=content, original_tokens=original_tokens, original_bytes=original_bytes)

        # LangGraph normally guarantees a call ID. Do not associate a payload
        # with an invented ID if a non-standard provider omitted one: that
        # could make two concurrent calls overwrite each other's continuation.
        if not tool_call_id.strip():
            return ToolOutputBinding(
                content=self._preview(
                    content,
                    preview_limit,
                    output_id=None,
                    expires_at=None,
                    storage_error="工具调用缺少 ID，完整结果无法安全暂存",
                ),
                original_tokens=original_tokens,
                original_bytes=original_bytes,
            )

        if original_bytes > self.storage_max_bytes:
            return ToolOutputBinding(
                content=self._preview(
                    content,
                    preview_limit,
                    output_id=None,
                    expires_at=None,
                    storage_error=(
                        f"原始结果超过服务器可保存上限 {self.storage_max_bytes // (1024 * 1024)} MiB；"
                        "请用更具体的源工具查询。"
                    ),
                ),
                original_tokens=original_tokens,
                original_bytes=original_bytes,
            )

        output_id = f"{OUTPUT_ID_PREFIX}{uuid4()}"
        expires_at = _now() + timedelta(days=self.retention_days)
        row = ChatToolOutput(
            output_id=output_id,
            document_id=self.document_id,
            session_id=self.session_id,
            run_id=self.run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=content,
            content_bytes=original_bytes,
            content_lines=_line_count(content),
            estimated_tokens=original_tokens,
            checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            retention_mode="ttl",
            expires_at=expires_at,
        )
        try:
            with SessionLocal() as db:
                db.add(row)
                db.commit()
        except IntegrityError:
            # A retried graph update may have already persisted this exact
            # call. Reuse the durable object instead of treating it as failure.
            with SessionLocal() as db:
                existing = db.query(ChatToolOutput).filter(
                    ChatToolOutput.run_id == self.run_id,
                    ChatToolOutput.tool_call_id == tool_call_id,
                ).first()
                if existing is None:
                    return ToolOutputBinding(
                        content=self._preview(content, preview_limit, output_id=None, expires_at=None, storage_error="完整结果暂存失败"),
                        original_tokens=original_tokens,
                        original_bytes=original_bytes,
                    )
                output_id = existing.output_id
                expires_at = existing.expires_at
        except SQLAlchemyError:
            return ToolOutputBinding(
                content=self._preview(content, preview_limit, output_id=None, expires_at=None, storage_error="完整结果暂存失败"),
                original_tokens=original_tokens,
                original_bytes=original_bytes,
            )

        return ToolOutputBinding(
            content=self._preview(content, preview_limit, output_id=output_id, expires_at=expires_at),
            output_id=output_id,
            stored=True,
            original_tokens=original_tokens,
            original_bytes=original_bytes,
        )

    @classmethod
    def preview_without_storage(cls, *, content: str, max_preview_tokens: int) -> ToolOutputBinding:
        """Return a bounded fallback for embedded/test-only graph callers.

        Production always provides a store. This still prevents a caller that
        has not configured persistence from accidentally placing an unbounded
        ToolMessage into the next provider request.
        """
        content = content if isinstance(content, str) else str(content)
        original_tokens = estimate_tokens(content)
        original_bytes = len(content.encode("utf-8"))
        preview_limit = max(MIN_PREVIEW_TOKENS, int(max_preview_tokens))
        if original_tokens <= preview_limit:
            return ToolOutputBinding(
                content=content,
                original_tokens=original_tokens,
                original_bytes=original_bytes,
            )
        return ToolOutputBinding(
            content=cls._preview(
                content,
                preview_limit,
                output_id=None,
                expires_at=None,
                storage_error="当前运行未启用完整结果暂存；请用更具体的源工具查询。",
            ),
            original_tokens=original_tokens,
            original_bytes=original_bytes,
        )

    @staticmethod
    def _preview(
        content: str,
        max_tokens: int,
        *,
        output_id: str | None,
        expires_at: datetime | None,
        storage_error: str = "",
    ) -> str:
        original_tokens = estimate_tokens(content)
        original_bytes = len(content.encode("utf-8"))
        metadata: dict[str, Any] = {
            "truncated": True,
            "estimated_original_tokens": original_tokens,
            "original_bytes": original_bytes,
            "original_lines": _line_count(content),
        }
        if output_id:
            metadata.update(
                {
                    "output_id": output_id,
                    "expires_at": expires_at.isoformat() if expires_at else "",
                    "next_step": "完整结果已暂存；请调用 read_tool_output(output_id, cursor?, max_tokens?) 按需继续读取。",
                }
            )
        else:
            metadata["next_step"] = storage_error or "请使用更具体的工具查询。"
        # Keep the continuation handle before the potentially long preview so
        # run compaction can retain it even when it only sees a short prefix.
        metadata["preview"] = {"head": "", "tail": ""}

        payload_budget = max(MIN_PREVIEW_TOKENS, max_tokens) - PREVIEW_METADATA_RESERVE_TOKENS
        per_side = max(32, payload_budget // 2)
        for _ in range(8):
            metadata["preview"] = {
                "head": _take_prefix(content, per_side),
                "tail": _take_suffix(content, per_side),
            }
            encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            if estimate_tokens(encoded) <= max_tokens:
                return encoded
            per_side = max(1, int(per_side * 0.7))
        metadata["preview"] = {"head": "", "tail": ""}
        return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

    def read_page(
        self,
        db: Session,
        *,
        output_id: str,
        cursor: str | None,
        max_tokens: int,
    ) -> str:
        row = db.get(ChatToolOutput, output_id)
        if row is None or row.document_id != self.document_id or row.session_id != self.session_id:
            raise ToolOutputError("完整工具结果不存在，或不属于当前文档与对话")
        if row.retention_mode == "ttl" and _is_expired(row.expires_at):
            raise ToolOutputError("完整工具结果已过期；请重新调用源工具获取当前数据")
        offset = _decode_cursor(cursor)
        if offset > len(row.content):
            raise ToolOutputError("工具结果游标超出范围，请从头重新读取")

        if max_tokens < 64:
            raise ToolOutputError("工具结果续读预算过小，请至少请求 64 tokens")
        envelope_reserve = min(512, max(128, max_tokens // 3))
        page_budget = max(64, max_tokens - envelope_reserve)
        remaining = row.content[offset:]
        page = _take_prefix(remaining, page_budget)
        if page and len(page) < len(remaining):
            newline = page.rfind("\n")
            if newline >= max(1, len(page) // 3):
                page = page[: newline + 1]
        next_offset = offset + len(page)
        def encode(value: str) -> str:
            value_end = offset + len(value)
            payload = {
                "output_id": row.output_id,
                "tool_name": row.tool_name,
                "cursor": _encode_cursor(offset),
                "content": value,
                "next_cursor": _encode_cursor(value_end) if value_end < len(row.content) else None,
                "remaining_bytes": len(row.content[value_end:].encode("utf-8")),
                "original_bytes": row.content_bytes,
                "original_lines": row.content_lines,
                "expires_at": row.expires_at.isoformat(),
            }
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        # JSON escaping and metadata are provider-token dependent. Validate
        # the final envelope instead of trusting a fixed reserve, while still
        # preserving whole-line pages whenever one fits.
        encoded = encode(page)
        while page and estimate_tokens(encoded) > max_tokens:
            page = _take_prefix(page, max(1, estimate_tokens(page) - max(1, estimate_tokens(encoded) - max_tokens)))
            encoded = encode(page)
        if estimate_tokens(encoded) > max_tokens:
            raise ToolOutputError("工具结果续读预算无法容纳响应元数据，请请求更大的窗口")
        return encoded


def cleanup_expired_tool_outputs(db: Session, *, now: datetime | None = None) -> int:
    """Delete expired full tool payloads while keeping compact event records."""
    expired_ids = [
        output_id
        for (output_id,) in (
            db.query(ChatToolOutput.output_id)
            .filter(ChatToolOutput.retention_mode == "ttl", ChatToolOutput.expires_at <= (now or _now()))
            .order_by(ChatToolOutput.expires_at, ChatToolOutput.output_id)
            .limit(500)
            .all()
        )
    ]
    if not expired_ids:
        return 0
    deleted = (
        db.query(ChatToolOutput)
        .filter(ChatToolOutput.output_id.in_(expired_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def tool_output_stats(db: Session, session_id: int) -> dict[str, int]:
    count, total_bytes, total_tokens = (
        db.query(
            func.count(ChatToolOutput.output_id),
            func.coalesce(func.sum(ChatToolOutput.content_bytes), 0),
            func.coalesce(func.sum(ChatToolOutput.estimated_tokens), 0),
        )
        .filter(ChatToolOutput.session_id == session_id)
        .one()
    )
    settings = get_settings()
    return {
        "stored_tool_output_count": int(count or 0),
        "stored_tool_output_bytes": int(total_bytes or 0),
        "stored_tool_output_tokens": int(total_tokens or 0),
        "tool_output_retention_days": int(settings.CHAT_TOOL_OUTPUT_RETENTION_DAYS),
        "tool_output_retention_mode": "ttl",
    }
