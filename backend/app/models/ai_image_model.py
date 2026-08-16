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
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    availability_time_ranges: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="all", server_default="all")
    adapter_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    provider = relationship("AIProvider", back_populates="image_models")
    allowed_users = relationship("User", secondary=image_model_user_access, back_populates="allowed_image_models")
    allowed_groups = relationship("UserGroup", secondary=image_model_group_access, back_populates="allowed_image_models")

    @property
    def allowed_user_ids(self) -> list[int]:
        return [user.id for user in self.allowed_users]

    @property
    def allowed_group_ids(self) -> list[int]:
        return [group.id for group in self.allowed_groups]

    @property
    def operations(self) -> list[str]:
        """Infer supported operations while allowing provider-specific overrides."""
        configured = self.adapter_config.get("operations") if isinstance(self.adapter_config, dict) else None
        if isinstance(configured, list):
            values = [str(item) for item in configured if str(item) in {"generate", "edit"}]
            if values:
                return list(dict.fromkeys(values))
        protocol = str(getattr(self.provider, "image_protocol", "") or "")
        name = self.model_name.lower()
        operations = ["generate"] if protocol else []
        if protocol == "openai_images" and ("gpt-image" in name or "image" in name):
            operations.append("edit")
        elif protocol == "dashscope_images" and ("image-edit" in name or "imageedit" in name or "wan2.7-image" in name or "wanx2.1-imageedit" in name):
            operations.append("edit")
        elif protocol == "volcengine_ark_images" and ("seedream" in name or "image" in name or "edit" in name):
            operations.append("edit")
        return list(dict.fromkeys(operations))
