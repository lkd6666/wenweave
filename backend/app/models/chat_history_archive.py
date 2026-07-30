from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE


class ChatHistoryArchive(Base):
    """A read-only suffix removed when a user re-asks an earlier request."""

    __tablename__ = "chat_history_archives"
    __table_args__ = (Index("ix_chat_history_archives_session_created", "session_id", "created_at"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_message_id: Mapped[int] = mapped_column(ID_TYPE, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="reask")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
