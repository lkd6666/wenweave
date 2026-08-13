from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ImageSearchOrientation = Literal["any", "landscape", "portrait", "square"]
ImageSearchTarget = Literal["cover", "body"]


class ImageSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    page: int = Field(default=1, ge=1, le=5)
    orientation: ImageSearchOrientation = "any"

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("搜图关键词至少需要 2 个字符")
        return normalized


class ImageSearchCandidateRead(BaseModel):
    id: str
    token: str
    preview_url: str
    title: str
    source_page_url: str
    engine: str
    width: int | None = None
    height: int | None = None
    format: str = ""


class ImageSearchResponse(BaseModel):
    query: str
    page: int
    next_page: int | None = None
    notice: str
    items: list[ImageSearchCandidateRead]


class ImageSearchApply(BaseModel):
    candidate_token: str = Field(min_length=20, max_length=16_000)
    target: ImageSearchTarget
    revision: str = Field(default="", max_length=64)
    anchor_block_id: str = Field(default="", max_length=128)
    expected_hash: str = Field(default="", max_length=64)
    source_image_url: str = Field(default="", max_length=4096)
    source_image_hash: str = Field(default="", max_length=64)
    target_image_index: int = Field(default=-1, ge=-1, le=10_000)
    alt: str = Field(default="", max_length=240)


class ImageSearchApplyResult(BaseModel):
    ok: bool = True
    target: Literal["cover", "body", "replace"]
    url: str
    revision: str = ""
