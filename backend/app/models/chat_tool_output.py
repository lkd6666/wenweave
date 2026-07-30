from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ChatToolOutput(Base):
    """A temporary, complete payload for a tool result that is too large to replay."""

    __tablename__ = "chat_tool_outputs"
    __table_args__ = (
        UniqueConstraint("run_id", "tool_call_id", name="uq_chat_tool_outputs_run_call"),
        Index("ix_chat_tool_outputs_session_expires", "session_id", "expires_at"),
    )

    output_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_call_id: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    content: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    content_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    # Complete payloads can be materially large.  Keep them only for a
    # configured TTL; the compact preview remains in the durable event log.
    retention_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="ttl", server_default="ttl")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
