from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_BINARY, LONG_TEXT


class ChatLayoutReference(Base):
    """Short-lived, user-scoped parsed reference shared by every worker."""

    __tablename__ = "chat_layout_references"

    reference_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    site_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    html_template: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_slots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extracted_from: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    warning: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    preview_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatLayoutReferenceAsset(Base):
    """Validated reference asset payload. Kept only until its reference TTL expires."""

    __tablename__ = "chat_layout_reference_assets"
    __table_args__ = (UniqueConstraint("reference_id", "asset_id", name="uq_chat_layout_reference_asset"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    reference_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_layout_references.reference_id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="正文图片")
    default_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data: Mapped[bytes] = mapped_column(LONG_BINARY, nullable=False)
