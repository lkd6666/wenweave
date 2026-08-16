from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE


class LayoutCaptureSession(Base):
    """Short-lived capability used by the browser extension exactly once."""

    __tablename__ = "layout_capture_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="layout_reference")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
