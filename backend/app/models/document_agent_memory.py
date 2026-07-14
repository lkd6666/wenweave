from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class DocumentAgentMemory(Base):
    """Compacted, document-level Agent memory.

    Source HTML is intentionally not stored here.  The current document
    workspace remains the source of truth, while this table retains only
    durable user intent and preferences from older chat turns.
    """

    __tablename__ = "document_agent_memories"
    __table_args__ = (UniqueConstraint("document_id", name="uq_document_agent_memories_document"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    compacted_through_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
