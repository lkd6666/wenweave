from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


GzhApplyMode = Literal["full", "restrained", "key_components"]


class GzhThemeRead(BaseModel):
    id: int | None = None
    key: str
    name: str
    description: str
    scenarios: list[str] = Field(default_factory=list)
    accent_color: str
    is_builtin: bool
    status: str = "published"
    preview_available: bool = False
    active_version_id: int | None = None
    active_version: int | None = None


class GzhThemeComponentRead(BaseModel):
    id: str
    name: str
    category: str
    source: Literal["theme", "common"]


class GzhThemeRecipeRead(BaseModel):
    id: str
    article_type: str
    core_component_ids: list[str] = Field(default_factory=list)
    decorative_component_ids: list[str] = Field(default_factory=list)


class GzhThemeManifestRead(BaseModel):
    schema_version: int
    source_checksum: str
    design_tokens: list[dict[str, str]] = Field(default_factory=list)
    components: list[GzhThemeComponentRead] = Field(default_factory=list)
    recipes: list[GzhThemeRecipeRead] = Field(default_factory=list)
    structural_component_ids: list[str] = Field(default_factory=list)
    recommended_recipe_id: str = ""


class GzhThemeProposalCreate(BaseModel):
    theme_key: str = Field(min_length=3, max_length=160)
    apply_mode: GzhApplyMode = "full"
    user_instructions: str = Field(default="", max_length=4000)
    article_type: str = Field(default="auto", max_length=128)
    recipe_id: str = Field(default="", max_length=128)
    selected_component_ids: list[str] = Field(default_factory=list, max_length=64)
    session_id: int | None = Field(default=None, gt=0)


class GzhThemeProposalRead(BaseModel):
    id: str
    theme_key: str
    theme_name: str
    apply_mode: GzhApplyMode
    user_instructions: str
    article_type: str = ""
    recipe_id: str = ""
    selected_component_ids: list[str] = Field(default_factory=list)
    status: str
    expires_at: datetime


class GzhThemeCreate(BaseModel):
    slug: str = Field(min_length=3, max_length=96, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    scenarios: list[str] = Field(default_factory=list, max_length=12)
    accent_color: str = Field(default="#1677ff", max_length=32)
    source_markdown: str = Field(min_length=200)
    preview_html: str = Field(default="")


class GzhThemePublishRead(GzhThemeRead):
    status: str


class GzhThemeVersionRead(BaseModel):
    id: int
    theme_id: int
    version: int
    status: str
    generation_brief: str = ""
    validation: list[dict[str, str]] = Field(default_factory=list)
    component_count: int = 0
    recipe_count: int = 0
    created_at: datetime
    published_at: datetime | None = None


class GzhThemeManagerRead(GzhThemeRead):
    versions: list[GzhThemeVersionRead] = Field(default_factory=list)


class GzhThemeReferenceAssetRead(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    expires_at: datetime


class GzhThemeGenerationCreate(BaseModel):
    model_id: int = Field(gt=0)
    brief: str = Field(min_length=8, max_length=4000)
    name_hint: str = Field(default="", max_length=128)
    slug_hint: str = Field(default="", max_length=96)
    accent_color: str = Field(default="", max_length=32)
    scenarios: list[str] = Field(default_factory=list, max_length=12)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=5)
    theme_id: int | None = Field(default=None, gt=0)


class GzhThemeGenerationRead(BaseModel):
    id: str
    status: str
    theme_id: int | None = None
    name_hint: str = ""
    slug_hint: str = ""
    brief: str
    validation: list[dict[str, str]] = Field(default_factory=list)
    error_message: str = ""
    preview_html: str = ""
    component_count: int = 0
    recipe_count: int = 0
    created_at: datetime
    finished_at: datetime | None = None


class GzhThemeGenerationSave(BaseModel):
    name: str = Field(default="", max_length=128)
    slug: str = Field(default="", max_length=96)
    description: str = Field(default="", max_length=1024)
    accent_color: str = Field(default="", max_length=32)
    scenarios: list[str] = Field(default_factory=list, max_length=12)
