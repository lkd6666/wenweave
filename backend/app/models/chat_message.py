from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT
from app.services.selected_elements import normalize_selected_elements

if TYPE_CHECKING:
    from app.models.chat_image_attachment import ChatImageAttachment
    from app.models.user import User


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A shared document can have requests from more than one collaborator.
    # Keep the request author on the message itself instead of inferring it
    # from whichever user is viewing the conversation.
    created_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    tool_calls_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    reasoning_trace_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    turn_blocks_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    selected_elements_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    template_refs_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    # The approved full-document theme request that created this message. It
    # lets a historical re-ask recover the same approval without trusting a
    # client-supplied proposal id.
    gzh_theme_proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 用户请求和 AI 修改均保存 HTML 快照，以便从任意历史请求安全创建新分支。
    html_before: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    html_after: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    is_superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Archived suffixes are retained for audit and a read-only UI, but never
    # participate in provider context or session-history retrieval.
    history_archive_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("chat_history_archives.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A compaction snapshot remains valid when it was created after an older
    # branch had already been superseded. Only later branch changes invalidate it.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship("Document", back_populates="messages")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    image_attachments: Mapped[list["ChatImageAttachment"]] = relationship(
        "ChatImageAttachment", back_populates="message", cascade="all, delete-orphan", order_by="ChatImageAttachment.created_at"
    )

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        """将存储字段转换为 API 使用的工具执行记录。"""
        try:
            value = json.loads(self.tool_calls_json or "[]")
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    @property
    def reasoning_trace(self) -> dict[str, Any]:
        """解析展示给用户的真实推理流；不会由系统伪造推理内容。"""
        try:
            value = json.loads(self.reasoning_trace_json or "{}")
        except json.JSONDecodeError:
            value = {}
        if not isinstance(value, dict):
            value = {}
        return {
            "status": value.get("status", "idle"),
            "content": value.get("content", ""),
            "detail": value.get("detail", ""),
        }

    @property
    def turn_blocks(self) -> list[dict[str, Any]]:
        """按真实 SSE 到达顺序保存的 thought / tool / content 块。"""
        try:
            value = json.loads(self.turn_blocks_json or "[]")
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    @property
    def selected_elements(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.selected_elements_json or "[]")
        except json.JSONDecodeError:
            return []
        return normalize_selected_elements(value)

    @property
    def template_refs(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.template_refs_json or "[]")
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    @property
    def can_revert(self) -> bool:
        return bool(self.html_before is not None and self.html_after is not None and not self.is_superseded)
