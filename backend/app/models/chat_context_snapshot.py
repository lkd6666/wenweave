from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ChatContextSnapshot(Base):
    """An immutable model-generated projection of an earlier event ledger prefix."""

    __tablename__ = "chat_context_snapshots"
    __table_args__ = (
        Index("ix_chat_context_snapshots_session_active", "session_id", "is_active"),
        # ``NULL`` is allowed more than once by both supported engines.  This
        # turns the active snapshot into a database-enforced singleton while
        # keeping every historical snapshot immutable and unbounded.
        UniqueConstraint("session_id", "active_slot", name="uq_chat_context_snapshots_active_slot"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_start_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compacted_through_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compacted_through_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retained_from_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="agentic")
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="automatic")
    model_id: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True)
    input_budget_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Cline-style source anchors prove that the compacted projection still
    # describes the active immutable ledger prefix after a historical re-ask.
    source_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_prefix_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    context_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    # Kept so a legacy lazily-invalidated snapshot can be recovered once, but
    # intentionally invalidated snapshots (rebuild, truncation, re-ask) cannot.
    invalidation_reason: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
