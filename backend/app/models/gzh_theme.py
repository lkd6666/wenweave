from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class GzhThemeStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class GzhThemeVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class GzhThemeGenerationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SAVED = "saved"


class GzhTheme(Base):
    """Stable custom-theme identity; content lives in immutable versions."""

    __tablename__ = "gzh_themes"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(96), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    scenarios: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accent_color: Mapped[str] = mapped_column(String(32), nullable=False, default="#1677ff")
    source_markdown: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    preview_html: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    # Legacy fields stay populated from the active version while existing
    # deployments and old Agent tools move to the version-aware service.
    active_version_id: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True, index=True)
    status: Mapped[GzhThemeStatus] = mapped_column(
        Enum(GzhThemeStatus, values_callable=lambda cls: [item.value for item in cls]),
        nullable=False,
        default=GzhThemeStatus.DRAFT,
    )
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GzhThemeVersion(Base):
    """A reviewable draft or published revision of one custom theme."""

    __tablename__ = "gzh_theme_versions"
    __table_args__ = (UniqueConstraint("theme_id", "version", name="uq_gzh_theme_versions_theme_version"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    theme_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("gzh_themes.id", ondelete="CASCADE"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_markdown: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    preview_html: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    manifest_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    validation_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    status: Mapped[GzhThemeVersionStatus] = mapped_column(
        Enum(GzhThemeVersionStatus, values_callable=lambda cls: [item.value for item in cls]),
        nullable=False,
        default=GzhThemeVersionStatus.DRAFT,
    )
    created_by_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GzhThemeReferenceAsset(Base):
    """Short-lived administrator-uploaded visual reference for theme generation."""

    __tablename__ = "gzh_theme_reference_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    uploader_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    object_key: Mapped[str] = mapped_column(String(768), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GzhThemeGeneration(Base):
    """Durable state for an asynchronous, review-before-save generation."""

    __tablename__ = "gzh_theme_generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # These are deliberately indexed logical references rather than database
    # foreign keys.  Existing MySQL deployments contain historical variants of
    # these tables with incompatible FK metadata; service-level ownership and
    # existence checks make the short-lived generation records safe to clean.
    theme_id: Mapped[int | None] = mapped_column(ID_TYPE, index=True, nullable=True)
    base_version_id: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True)
    model_id: Mapped[int] = mapped_column(ID_TYPE, nullable=False)
    user_id: Mapped[int] = mapped_column(ID_TYPE, index=True, nullable=False)
    name_hint: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    slug_hint: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    accent_color: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    scenarios_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    reference_asset_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    validation_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    error_message: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    status: Mapped[GzhThemeGenerationStatus] = mapped_column(
        Enum(GzhThemeGenerationStatus, values_callable=lambda cls: [item.value for item in cls]),
        nullable=False,
        default=GzhThemeGenerationStatus.PENDING,
    )
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
