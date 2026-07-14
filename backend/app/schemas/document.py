from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentSourceType
from app.models.document_version import DocumentVersionSource


class UserReference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str


VisibilityMode = Literal["all", "restricted"]


class VisibilitySettings(BaseModel):
    visibility_mode: VisibilityMode = "all"
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)


class VisibilityUserTarget(UserReference):
    is_active: bool


class VisibilityGroupTarget(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class VisibilityTargetsRead(BaseModel):
    users: list[VisibilityUserTarget]
    groups: list[VisibilityGroupTarget]


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source_type: DocumentSourceType
    group_id: int | None
    visibility_mode: VisibilityMode
    allowed_user_ids: list[int]
    allowed_group_ids: list[int]
    created_by: UserReference | None
    last_modified_by: UserReference | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    current_html: str


class DocumentSourceAccess(BaseModel):
    filename: str
    content_type: str
    size: int
    url: str
    expires_in_seconds: int


class DirectUploadTarget(BaseModel):
    object_key: str
    content_type: str
    upload_url: str
    expires_in_seconds: int


class DocumentImportCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=128)
    size: int = Field(gt=0)


class DocumentImportCreateResult(BaseModel):
    id: str
    source_type: DocumentSourceType
    source_upload: DirectUploadTarget
    expires_at: datetime


class DocumentImportAssetCreate(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=128)
    size: int = Field(gt=0)


class DocumentImportAssetUpload(BaseModel):
    client_id: str
    asset_id: str
    upload: DirectUploadTarget


class DocumentImportAssetsCreate(BaseModel):
    assets: list[DocumentImportAssetCreate] = Field(min_length=1, max_length=200)


class DocumentImportAssetsResult(BaseModel):
    assets: list[DocumentImportAssetUpload]


class DocumentImportComplete(BaseModel):
    html: str = Field(min_length=1, max_length=10 * 1024 * 1024)
    title: str | None = Field(default=None, max_length=256)
    group_id: int | None = None


class DocumentImportStatusRead(BaseModel):
    id: str
    status: str
    source_upload: DirectUploadTarget | None
    assets: list[DocumentImportAssetUpload] = Field(default_factory=list)
    expires_at: datetime
    document_id: int | None = None


class DocumentVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    title: str
    source: DocumentVersionSource
    label: str
    created_by: UserReference | None
    created_at: datetime


class DocumentVersionDetail(DocumentVersionSummary):
    html: str


class DocumentCreate(VisibilitySettings):
    title: str = Field(default="未命名排版", max_length=256)
    group_id: int | None = None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    current_html: str | None = None
    group_id: int | None = None
    visibility_mode: VisibilityMode | None = None
    allowed_user_ids: list[int] | None = None
    allowed_group_ids: list[int] | None = None


class DocumentImageUpload(BaseModel):
    url: str


class DocumentGroupCreate(VisibilitySettings):
    name: str = Field(min_length=1, max_length=128)


class DocumentGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    visibility_mode: VisibilityMode | None = None
    allowed_user_ids: list[int] | None = None
    allowed_group_ids: list[int] | None = None


class DocumentGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    visibility_mode: VisibilityMode
    allowed_user_ids: list[int]
    allowed_group_ids: list[int]
    created_by: UserReference | None
    created_at: datetime
    updated_at: datetime
    has_source_file: bool = False
    last_modified_by: UserReference | None
