from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, MEDIUM_TEXT


class DocumentShare(Base):
    """A revocable capability link for the current read-only document view."""

    __tablename__ = "document_shares"
    __table_args__ = (
        Index("ix_document_shares_document_created", "document_id", "created_at"),
        Index("ix_document_shares_expiry", "expires_at", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_encrypted: Mapped[str] = mapped_column(MEDIUM_TEXT, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by_display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_by_username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    revoked_by_display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document = relationship("Document", foreign_keys=[document_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    revoked_by = relationship("User", foreign_keys=[revoked_by_id])
    visits: Mapped[list["DocumentShareVisit"]] = relationship("DocumentShareVisit", back_populates="share")


class DocumentShareVisit(Base):
    """One durable, anonymous browser session entry for a share link."""

    __tablename__ = "document_share_visits"
    __table_args__ = (
        UniqueConstraint("share_id", "visitor_session_hash", name="uq_document_share_visit_session"),
        Index("ix_document_share_visits_share_seen", "share_id", "first_seen_at"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    share_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("document_shares.id", ondelete="SET NULL"), nullable=True, index=True
    )
    visitor_session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    referer: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    share: Mapped[DocumentShare | None] = relationship("DocumentShare", back_populates="visits")
