from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TemplateCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=-10000, le=10000)


class TemplateCategoryUpdate(TemplateCategoryCreate):
    pass


class TemplateCategoryRead(BaseModel):
    id: int
    name: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class TemplateImageWarning(BaseModel):
    source: str
    message: str


class TemplateItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category_id: int | None = Field(default=None, gt=0)
    html: str = Field(min_length=1, max_length=400_000)
    source_type: Literal["rich_paste", "source", "ai"] = "source"


class TemplateItemUpdate(TemplateItemCreate):
    pass


class TemplateItemRead(BaseModel):
    id: int
    name: str
    category_id: int | None
    source_type: Literal["rich_paste", "source", "ai"]
    html: str
    image_warnings: list[TemplateImageWarning] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TemplateImageLocalizationItem(BaseModel):
    template_id: int
    name: str
    status: Literal["updated", "unchanged", "failed"]
    localized_count: int = 0
    message: str = ""


class TemplateImageLocalizationResult(BaseModel):
    items: list[TemplateImageLocalizationItem] = Field(default_factory=list)
    updated_count: int = 0
    failed_count: int = 0
    localized_count: int = 0


class TemplateGenerationCreate(BaseModel):
    model_id: int = Field(gt=0)
    prompt: str = Field(min_length=4, max_length=6000)


class TemplateGenerationRead(BaseModel):
    id: str
    status: Literal["pending", "running", "succeeded", "failed", "cancelled", "saved"]
    prompt: str
    output_html: str = ""
    error_message: str = ""
    created_at: datetime
    finished_at: datetime | None = None


class TemplateGenerationSave(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category_id: int | None = Field(default=None, gt=0)
