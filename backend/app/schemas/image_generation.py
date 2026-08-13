from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ImagePurpose = Literal["cover", "body"]
ImageSource = Literal["editor", "agent"]
ImageStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
ImageOperation = Literal["generate", "edit"]
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
    library_asset_id: str = ""
    library_url: str = ""
    is_applied: bool
    is_currently_applied: bool = False
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
    operation: ImageOperation = "generate"
    prompt: str
    quantity: int
    aspect_ratio: ImageAspectRatio
    quality: str
    timeout_seconds: int = 180
    anchor_block_id: str = ""
    source_image_url: str = ""
    source_image_hash: str = ""
    source_asset_url: str = ""
    target_image_index: int = -1
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
    purpose: ImagePurpose = "body"
    operation: ImageOperation = "generate"
    prompt: str = Field(min_length=3, max_length=8_000)
    quantity: int = Field(ge=1, le=4)
    aspect_ratio: ImageAspectRatio = "landscape"
    quality: str = Field(default="auto", max_length=24)
    timeout_seconds: int = Field(default=180, ge=30, le=1800)
    anchor_block_id: str = Field(default="", max_length=128)
    source_image_url: str = Field(default="", max_length=4096)
    target_image_index: int = Field(default=-1, ge=-1, le=10000)
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
    source_image_url: str = Field(default="", max_length=4096)
    source_image_hash: str = Field(default="", max_length=64)
    target_image_index: int = Field(default=-1, ge=-1, le=10000)
    alt: str = Field(default="", max_length=240)


class ImageGenerationWorkspaceResolve(BaseModel):
    """A preview DOM selection that must resolve to a current HTML block."""

    selector: str = Field(min_length=1, max_length=1024)
    tag_name: str = Field(min_length=1, max_length=64)
    text: str = Field(default="", max_length=1_000)
    html: str = Field(default="", max_length=12_000)
    locator: dict[str, Any] | None = None
