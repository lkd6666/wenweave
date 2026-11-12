from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ChatTextAttachment(Base):
    """Immutable UTF-8 data; content is never eagerly loaded with a message."""
    __tablename__ = "chat_text_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    uploader_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(160))
    size: Mapped[int] = mapped_column(Integer)
    characters: Mapped[int] = mapped_column(Integer)
    lines: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(LONG_TEXT, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    message: Mapped["ChatMessage | None"] = relationship("ChatMessage", back_populates="text_attachments")
