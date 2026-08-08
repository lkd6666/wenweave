from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ImagePurpose = Literal["cover", "body"]
ImageSource = Literal["editor", "agent"]
ImageStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
ImageAspectRatio = Literal["square", "portrait", "landscape"]


class GeneratedImageAssetRead(BaseModel):
    id: str
    generation_id: str
    url: str
    content_type: str
    size: int
    width: int
    height: int
    revised_prompt: str = ""
    is_applied: bool
    applied_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ImageGenerationRead(BaseModel):
    id: str
    document_id: int
    session_id: int | None = None
    model_id: int
    source: ImageSource
    purpose: ImagePurpose
    prompt: str
    quantity: int
    aspect_ratio: ImageAspectRatio
    quality: str
    anchor_block_id: str = ""
    direct_insert: bool = False
    status: ImageStatus
    error_message: str = ""
    usage: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    assets: list[GeneratedImageAssetRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ImageGenerationCreate(BaseModel):
    model_id: int = Field(gt=0)
    session_id: int | None = Field(default=None, gt=0)
    purpose: ImagePurpose
    prompt: str = Field(min_length=3, max_length=8_000)
    quantity: int = Field(ge=1, le=4)
    aspect_ratio: ImageAspectRatio = "landscape"
    quality: str = Field(default="auto", max_length=24)
    anchor_block_id: str = Field(default="", max_length=128)
    direct_insert: bool = False

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("图片描述不能为空")
        return normalized


class ImageGenerationApply(BaseModel):
    target: ImagePurpose
    # Required for a body insertion. It is the HTML workspace revision shown
    # to the editor/Agent before it selected the target block.
    revision: str = Field(default="", max_length=64)
    anchor_block_id: str = Field(default="", max_length=128)
    expected_hash: str = Field(default="", max_length=64)
    alt: str = Field(default="", max_length=240)


class ChatImageGenerationSettingsUpdate(BaseModel):
    image_model_id: int | None = Field(default=None, gt=0)
    auto_image_generation_enabled: bool = False

