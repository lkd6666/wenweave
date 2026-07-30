from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class GzhThemeProposalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    APPLIED = "applied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class GzhThemeProposal(Base):
    __tablename__ = "gzh_theme_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    theme_key: Mapped[str] = mapped_column(String(160), nullable=False)
    theme_name: Mapped[str] = mapped_column(String(128), nullable=False)
    theme_markdown: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    # A derived, read-only description of the vendored component library.  The
    # original Markdown remains the source of truth; this snapshot fixes the
    # selected recipe and component meanings for an approved proposal.
    theme_manifest_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    theme_manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    article_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    recipe_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    selected_component_ids_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    apply_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="full")
    user_instructions: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    base_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[GzhThemeProposalStatus] = mapped_column(
        Enum(GzhThemeProposalStatus, values_callable=lambda cls: [item.value for item in cls]),
        nullable=False,
        default=GzhThemeProposalStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
