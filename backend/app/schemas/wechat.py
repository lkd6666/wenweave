from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WeChatArticleMetadata(BaseModel):
    # Editor metadata must round-trip the canonical document title. Enforce
    # WeChat's 64-character limit when syncing, before making a remote request.
    title: str = Field(default="", max_length=256)
    author: str = Field(default="", max_length=16)
    digest: str = Field(default="", max_length=120)
    content_source_url: str = Field(default="", max_length=1024)
    cover_url: str = Field(default="", max_length=2048)
    pic_crop_235_1: str = Field(default="", max_length=128)
    pic_crop_1_1: str = Field(default="", max_length=128)
    need_open_comment: bool = False
    only_fans_can_comment: bool = False

    @field_validator("title", "author", "digest", "content_source_url", "cover_url", "pic_crop_235_1", "pic_crop_1_1")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("content_source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("原文链接必须以 http:// 或 https:// 开头")
        return value

    @field_validator("pic_crop_235_1", "pic_crop_1_1")
    @classmethod
    def validate_crop(cls, value: str) -> str:
        if not value:
            return value
        parts = value.split("_")
        if len(parts) != 4:
            raise ValueError("封面裁剪坐标格式无效")
        try:
            x1, y1, x2, y2 = (Decimal(part) for part in parts)
        except InvalidOperation as exc:
            raise ValueError("封面裁剪坐标格式无效") from exc
        if not (Decimal(0) <= x1 < x2 <= Decimal(1) and Decimal(0) <= y1 < y2 <= Decimal(1)):
            raise ValueError("封面裁剪坐标必须位于 0 到 1 之间")
        return value


class WeChatAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    app_id: str = Field(min_length=1, max_length=64)
    app_secret: str = Field(min_length=1, max_length=512)
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)
    is_active: bool = True

    @field_validator("name", "app_id")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class WeChatAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    app_id: str | None = Field(default=None, min_length=1, max_length=64)
    app_secret: str | None = Field(default=None, max_length=512)
    allowed_user_ids: list[int] | None = None
    allowed_group_ids: list[int] | None = None
    is_active: bool | None = None

    @field_validator("name", "app_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class WeChatAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    app_id: str
    app_secret_masked: str
    allowed_user_ids: list[int]
    allowed_group_ids: list[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WeChatAvailableAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class WeChatAccountTestResult(BaseModel):
    success: bool
    message: str


class WeChatDraftCreate(BaseModel):
    account_id: int
    sync_mode: Literal["auto", "create", "update"] = "auto"
    target_media_id: str = Field(default="", max_length=512)

    @field_validator("target_media_id")
    @classmethod
    def strip_target_media_id(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_sync_target(self) -> "WeChatDraftCreate":
        if self.sync_mode == "update" and not self.target_media_id:
            raise ValueError("覆盖原图文时必须选择要覆盖的草稿")
        if self.sync_mode in {"auto", "create"} and self.target_media_id:
            raise ValueError("自动或新建同步时不能指定要覆盖的草稿")
        return self


class WeChatDraftTargetRead(BaseModel):
    media_id: str
    title: str
    update_time: int | None = None
    article_count: int = Field(ge=1)


class WeChatDraftRead(BaseModel):
    id: int
    account_id: int
    account_name: str
    status: str
    media_id: str | None
    sync_mode: Literal["create", "update"]
    article_title: str
    error_code: int | None
    error_message: str
    created_by_name: str | None
    created_at: datetime


class WeChatCoverUpload(BaseModel):
    url: str
