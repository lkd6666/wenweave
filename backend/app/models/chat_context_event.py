from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ContextEventKind(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatContextEvent(Base):
    """An immutable provider-visible message in a session transcript.

    ``payload_json`` deliberately stores the canonical LangChain-compatible
    fields instead of UI timeline data. The latter may contain streamed
    reasoning or display-only tool summaries which must never be replayed to a
    provider on the next user turn.
    """

    __tablename__ = "chat_context_events"
    __table_args__ = (
        UniqueConstraint("session_id", "message_id", "ordinal", name="uq_context_event_message_ordinal"),
        Index("ix_chat_context_events_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[ContextEventKind] = mapped_column(Enum(ContextEventKind), nullable=False)
    payload_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    document_revision: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    is_legacy: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
        except json.JSONDecodeError:
            value = {}
        return value if isinstance(value, dict) else {}
