from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_BINARY, LONG_TEXT


class WebArticleImportStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class WebArticleImport(Base):
    """Short-lived, user-owned preview content for a public article import."""

    __tablename__ = "web_article_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="未命名推文")
    html_template: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    warnings_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cover_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cover_requires_crops: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preview_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[WebArticleImportStatus] = mapped_column(
        Enum(WebArticleImportStatus), nullable=False, default=WebArticleImportStatus.PENDING
    )
    document_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    assets: Mapped[list["WebArticleImportAsset"]] = relationship(
        "WebArticleImportAsset", back_populates="import_session", cascade="all, delete-orphan"
    )


class WebArticleImportAsset(Base):
    __tablename__ = "web_article_import_assets"
    __table_args__ = (UniqueConstraint("import_id", "asset_id", name="uq_web_article_import_asset"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    import_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("web_article_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[bytes] = mapped_column(LONG_BINARY, nullable=False)

    import_session: Mapped[WebArticleImport] = relationship("WebArticleImport", back_populates="assets")
