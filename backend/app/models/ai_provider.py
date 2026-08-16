from __future__ import annotations

import enum
from datetime import datetime
from typing import List

from sqlalchemy import JSON, Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, MEDIUM_TEXT


class ProviderType(str, enum.Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC = "anthropic"


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[ProviderType] = mapped_column(Enum(ProviderType), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # Chat keeps its established protocol configuration above.  A provider may
    # additionally expose one native image-generation endpoint using the same
    # encrypted credential.  Empty values mean that image generation is not
    # configured for this provider.
    image_protocol: Mapped[str] = mapped_column(String(48), nullable=False, default="", server_default="")
    image_base_url: Mapped[str] = mapped_column(String(512), nullable=False, default="", server_default="")
    # Availability is independent from per-model visibility permissions. A disabled
    # provider remains configurable by administrators but cannot serve new calls.
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    # Empty means available all day. Ranges are evaluated in Asia/Shanghai by
    # model_access before a new request is allowed.
    availability_time_ranges: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    api_key_encrypted: Mapped[str] = mapped_column(MEDIUM_TEXT, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    models: Mapped[List["AIModel"]] = relationship(
        "AIModel", back_populates="provider", cascade="all, delete-orphan"
    )
    image_models: Mapped[List["AIImageModel"]] = relationship(
        "AIImageModel", back_populates="provider", cascade="all, delete-orphan"
    )
