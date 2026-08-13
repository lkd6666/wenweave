from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ImageLibraryModeValue = Literal["personal", "shared"]
ImageLibrarySourceValue = Literal["upload", "ai", "search"]


class ImageLibrarySettingsRead(BaseModel):
    mode: ImageLibraryModeValue
    updated_at: datetime | None = None


class ImageLibrarySettingsUpdate(BaseModel):
    mode: ImageLibraryModeValue
    shared_asset_ids: list[str] = Field(default_factory=list, max_length=10_000)


class ImageLibraryAssetRead(BaseModel):
    id: str
    owner_id: int
    owner_name: str
    document_id: int | None = None
    generation_id: str = ""
    generated_asset_id: str = ""
    name: str
    source: ImageLibrarySourceValue
    url: str
    content_type: str
    size: int
    width: int
    height: int
    is_shared: bool
    can_manage: bool
    created_at: datetime
    updated_at: datetime


class ImageLibraryListRead(BaseModel):
    items: list[ImageLibraryAssetRead]
    total: int
    page: int
    page_size: int
    mode: ImageLibraryModeValue


class ImageLibraryAssetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class ImageLibraryBulkDelete(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=500)


class ImageLibraryCoverApply(BaseModel):
    document_id: int = Field(gt=0)


class ImageLibrarySearchImport(BaseModel):
    document_id: int = Field(gt=0)
    candidate_token: str = Field(min_length=1, max_length=20_000)
