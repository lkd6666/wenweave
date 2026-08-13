from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ImageGenerationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImageGenerationSource(str, enum.Enum):
    EDITOR = "editor"
    AGENT = "agent"


class ImageGenerationPurpose(str, enum.Enum):
    COVER = "cover"
    BODY = "body"


class ImageGenerationOperation(str, enum.Enum):
    GENERATE = "generate"
    EDIT = "edit"


class ImageLibraryMode(str, enum.Enum):
    PERSONAL = "personal"
    SHARED = "shared"


class ImageLibrarySource(str, enum.Enum):
    UPLOAD = "upload"
    AI = "ai"
    SEARCH = "search"


class ImageGeneration(Base):
    """Durable work item for one provider image-generation request."""

    __tablename__ = "image_generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("ai_image_models.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[ImageGenerationSource] = mapped_column(
        Enum(ImageGenerationSource, values_callable=lambda values: [item.value for item in values]), nullable=False
    )
    purpose: Mapped[ImageGenerationPurpose] = mapped_column(
        Enum(ImageGenerationPurpose, values_callable=lambda values: [item.value for item in values]), nullable=False
    )
    operation: Mapped[ImageGenerationOperation] = mapped_column(
        Enum(ImageGenerationOperation, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=ImageGenerationOperation.GENERATE,
        server_default="generate",
    )
    prompt: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aspect_ratio: Mapped[str] = mapped_column(String(24), nullable=False, default="landscape")
    quality: Mapped[str] = mapped_column(String(24), nullable=False, default="auto")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=180, server_default="180")
    anchor_block_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_image_url: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    source_image_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_asset_url: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    source_object_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    source_storage_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="")
    target_image_index: Mapped[int] = mapped_column(Integer, nullable=False, default=-1, server_default="-1")
    direct_insert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_task_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[ImageGenerationStatus] = mapped_column(
        Enum(ImageGenerationStatus, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=ImageGenerationStatus.PENDING,
        index=True,
    )
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    usage_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    error_message: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    model = relationship("AIImageModel")
    assets = relationship("GeneratedImageAsset", back_populates="generation", cascade="all, delete-orphan")


class GeneratedImageAsset(Base):
    """A validated output saved to application-controlled storage."""

    __tablename__ = "generated_image_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    generation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("image_generations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Generated keys are short UUID-based paths. Keep the indexed column below
    # MySQL's utf8mb4 3072-byte index limit when create_all runs on a fresh DB.
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    storage_mode: Mapped[str] = mapped_column(String(12), nullable=False)
    url: Mapped[str] = mapped_column(String(4096), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revised_prompt: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    is_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    generation = relationship("ImageGeneration", back_populates="assets")


class ImageLibraryAsset(Base):
    """Reusable user-owned image material, uploaded or produced by AI."""

    __tablename__ = "image_library_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    generation_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", index=True)
    generated_asset_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="图片")
    source: Mapped[ImageLibrarySource] = mapped_column(
        Enum(ImageLibrarySource, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=ImageLibrarySource.UPLOAD,
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    storage_mode: Mapped[str] = mapped_column(String(12), nullable=False)
    url: Mapped[str] = mapped_column(String(4096), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ImageLibrarySettings(Base):
    """Single global switch controlling personal or shared library visibility."""

    __tablename__ = "image_library_settings"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=False)
    mode: Mapped[ImageLibraryMode] = mapped_column(
        Enum(ImageLibraryMode, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=ImageLibraryMode.PERSONAL,
        server_default="personal",
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
