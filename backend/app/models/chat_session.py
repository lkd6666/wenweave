from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ChatSession(Base):
    """A document-scoped conversation with an independently resettable context."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="新对话")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # Messages at or below this ID remain available as read-only history but
    # are never supplied to the model or its durable compacted memory.
    context_start_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Advances whenever the model-visible history is explicitly reset or restored.
    context_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    image_model_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("ai_image_models.id", ondelete="SET NULL"), nullable=True, index=True
    )
    auto_image_generation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    image_model = relationship("AIImageModel")


class ChatSessionMemory(Base):
    """Durable compacted memory for exactly one chat session."""

    __tablename__ = "chat_session_memories"
    __table_args__ = (UniqueConstraint("session_id", name="uq_chat_session_memories_session"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    compacted_through_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # New context replay is event-based. Keep the message boundary during the
    # online migration so existing databases can be backfilled safely.
    compacted_through_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compaction_strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    summary_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatSessionTemplateAttachment(Base):
    """An ordered, durable component-library selection for one chat session."""

    __tablename__ = "chat_session_template_attachments"
    __table_args__ = (
        UniqueConstraint("session_id", "template_id", name="uq_chat_session_template_attachment"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("template_library_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSessionThemeContext(Base):
    """The theme proposal intentionally kept as context for one conversation."""

    __tablename__ = "chat_session_theme_contexts"
    __table_args__ = (UniqueConstraint("session_id", name="uq_chat_session_theme_context_session"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gzh_theme_proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gzh_theme_proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
