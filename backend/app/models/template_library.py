from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class TemplateSourceType(str, enum.Enum):
    RICH_PASTE = "rich_paste"
    SOURCE = "source"
    AI = "ai"


class TemplateGenerationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SAVED = "saved"


class TemplateCategory(Base):
    __tablename__ = "template_categories"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TemplateLibraryItem(Base):
    __tablename__ = "template_library_items"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("template_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    html: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    source_type: Mapped[TemplateSourceType] = mapped_column(
        Enum(TemplateSourceType, values_callable=lambda cls: [item.value for item in cls]),
        nullable=False,
        default=TemplateSourceType.SOURCE,
    )
    image_warnings_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    created_by_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)


class TemplateImageAsset(Base):
    __tablename__ = "template_image_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("template_library_items.id", ondelete="CASCADE"), nullable=False, index=True)
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    object_key: Mapped[str] = mapped_column(String(768), nullable=False, unique=True)
    storage_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateGeneration(Base):
    __tablename__ = "template_generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("ai_models.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    output_html: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    status: Mapped[TemplateGenerationStatus] = mapped_column(
        Enum(TemplateGenerationStatus, values_callable=lambda cls: [item.value for item in cls]),
        nullable=False,
        default=TemplateGenerationStatus.PENDING,
    )
    cancel_requested: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
