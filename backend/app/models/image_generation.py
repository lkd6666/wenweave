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
    prompt: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aspect_ratio: Mapped[str] = mapped_column(String(24), nullable=False, default="landscape")
    quality: Mapped[str] = mapped_column(String(24), nullable=False, default="auto")
    anchor_block_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
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
