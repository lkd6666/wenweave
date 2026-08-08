from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE
from app.models.user_group import image_model_group_access, image_model_user_access


class AIImageModel(Base):
    """A text-to-image model attached to a shared provider credential."""

    __tablename__ = "ai_image_models"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    # Provider adapters map these portable values to their native parameters.
    supported_aspect_ratios: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    supported_qualities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="all", server_default="all")
    adapter_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider = relationship("AIProvider", back_populates="image_models")
    allowed_users = relationship("User", secondary=image_model_user_access, back_populates="allowed_image_models")
    allowed_groups = relationship("UserGroup", secondary=image_model_group_access, back_populates="allowed_image_models")

    @property
    def allowed_user_ids(self) -> list[int]:
        return [user.id for user in self.allowed_users]

    @property
    def allowed_group_ids(self) -> list[int]:
        return [group.id for group in self.allowed_groups]
