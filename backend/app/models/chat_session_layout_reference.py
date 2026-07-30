from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ChatSessionLayoutReference(Base):
    """The currently bound, source-safe layout template for one chat session."""

    __tablename__ = "chat_session_layout_references"
    __table_args__ = (UniqueConstraint("session_id", name="uq_chat_session_layout_reference_session"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="未命名参考文章")
    site_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    extracted_from: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    html_template: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    block_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_slots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_assets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imitation_strength: Mapped[str] = mapped_column(String(16), nullable=False, default="structure")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
