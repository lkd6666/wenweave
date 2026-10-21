from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LayoutReferencePreviewRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class LayoutCaptureSessionRead(BaseModel):
    id: str
    token: str
    canonical_url: str
    expires_at: datetime
    purpose: Literal["layout_reference", "web_article_import"] = "layout_reference"

    @field_validator("expires_at")
    @classmethod
    def normalise_expires_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class LayoutCaptureAssetManifest(BaseModel):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    content_type: str = Field(min_length=1, max_length=64)
    size: int = Field(gt=0, le=10 * 1024 * 1024)


class LayoutCaptureManifest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    omitted_asset_count: int = Field(default=0, ge=0, le=1000)
    cover_asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    assets: list[LayoutCaptureAssetManifest] = Field(default_factory=list, max_length=200)


class LayoutReferenceSummary(BaseModel):
    block_count: int
    image_slots: int
    image_assets: int
    extracted_from: str


class LayoutReferenceAssetPreview(BaseModel):
    asset_id: str
    preview_url: str
    content_type: str
    width: int = 0
    height: int = 0
    usage_count: int = 0
    role: str
    default_selected: bool = False


class LayoutReferencePreview(BaseModel):
    reference_id: str
    canonical_url: str
    title: str
    site_name: str
    preview_html: str
    assets: list[LayoutReferenceAssetPreview] = Field(default_factory=list)
    summary: LayoutReferenceSummary
    requires_asset_reuse_confirmation: bool = False
    warning: str | None = None
