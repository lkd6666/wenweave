from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings
from app.models.document import DocumentSourceType
from app.models.document_version import DocumentVersionSource
from app.schemas.wechat import WeChatArticleMetadata
from app.schemas.html_validation import HtmlValidationReportRead


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
    wechat_cover_url: str
    is_ai_editing: bool = False
    created_by: UserReference | None
    last_modified_by: UserReference | None
    created_at: datetime
    updated_at: datetime


class DocumentAiEditingStatus(BaseModel):
    active_document_ids: list[int] = Field(default_factory=list)


class DocumentDetail(DocumentSummary):
    current_html: str
    wechat_metadata: WeChatArticleMetadata
    html_validation: HtmlValidationReportRead | None = None


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
    upload_method: Literal["PUT", "POST"] = "PUT"
    upload_headers: dict[str, str] = Field(default_factory=dict)
    upload_fields: dict[str, str] = Field(default_factory=dict)
    file_field_name: str = "file"
    expires_in_seconds: int


class DocumentImportCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=128)
    size: int = Field(gt=0)


class DocumentImportCreateResult(BaseModel):
    id: str
    source_type: DocumentSourceType
    upload_mode: Literal["oss", "server"]
    source_upload: DirectUploadTarget | None = None
    expires_at: datetime


class DocumentImportAssetCreate(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=128)
    size: int = Field(gt=0)


class DocumentImportAssetUpload(BaseModel):
    client_id: str
    asset_id: str
    upload: DirectUploadTarget | None = None


class DocumentImportAssetsCreate(BaseModel):
    assets: list[DocumentImportAssetCreate] = Field(min_length=1, max_length=400)


class DocumentImportAssetsResult(BaseModel):
    assets: list[DocumentImportAssetUpload]


class DocumentImportComplete(BaseModel):
    html: str = Field(min_length=1, max_length=10 * 1024 * 1024)
    title: str | None = Field(default=None, max_length=256)
    group_id: int | None = None

    @field_validator("html")
    @classmethod
    def limit_html_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > get_settings().MAX_DOCUMENT_HTML_BYTES:
            raise ValueError("HTML 内容超过允许大小")
        return value


class DocumentImportStatusRead(BaseModel):
    id: str
    status: str
    upload_mode: Literal["oss", "server"]
    source_upload: DirectUploadTarget | None
    assets: list[DocumentImportAssetUpload] = Field(default_factory=list)
    expires_at: datetime
    document_id: int | None = None


class WebArticleImportPreviewRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class WebArticleImportPreview(BaseModel):
    id: str
    title: str
    preview_html: str
    cover_preview_url: str | None = None
    cover_requires_crops: bool = False
    image_count: int
    imported_image_count: int
    external_image_count: int
    warnings: list[str] = Field(default_factory=list)
    expires_at: datetime


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

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("标题不能为空")
        return normalized


class DocumentVersionCopyCreate(VisibilitySettings):
    """Target metadata for a document created from an immutable version."""

    title: str = Field(min_length=1, max_length=256)
    group_id: int | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("标题不能为空")
        return normalized


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    current_html: str | None = Field(default=None, max_length=get_settings().MAX_DOCUMENT_HTML_BYTES)
    wechat_metadata: WeChatArticleMetadata | None = None
    group_id: int | None = None
    visibility_mode: VisibilityMode | None = None
    allowed_user_ids: list[int] | None = None
    allowed_group_ids: list[int] | None = None

    @field_validator("current_html")
    @classmethod
    def limit_current_html_bytes(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > get_settings().MAX_DOCUMENT_HTML_BYTES:
            raise ValueError("HTML 内容超过允许大小")
        return value

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("标题不能为空")
        return normalized


class DocumentHtmlPatch(BaseModel):
    """A Unicode-code-point splice against the last persisted document HTML."""

    base_checksum: str = Field(min_length=64, max_length=64)
    prefix_length: int = Field(ge=0)
    suffix_length: int = Field(ge=0)
    replacement: str = Field(max_length=get_settings().MAX_DOCUMENT_HTML_BYTES)

    @field_validator("replacement")
    @classmethod
    def limit_replacement_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > get_settings().MAX_DOCUMENT_HTML_BYTES:
            raise ValueError("HTML 补丁超过允许大小")
        return value


class DocumentImageLocalizationResult(BaseModel):
    html: str
    localized_count: int
    html_validation: HtmlValidationReportRead | None = None


class DocumentShareCreate(BaseModel):
    expires_at: datetime


class DocumentShareUpdate(BaseModel):
    expires_at: datetime


class DocumentShareRead(BaseModel):
    id: int
    document_id: int | None
    document_title: str
    token: str
    created_by_id: int | None
    created_by_username: str
    created_by_display_name: str
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by_id: int | None
    revoked_by_username: str
    revoked_by_display_name: str
    created_at: datetime
    is_active: bool
    visit_count: int
    last_visited_at: datetime | None


class DocumentShareVisitRead(BaseModel):
    id: int
    ip_address: str
    user_agent: str
    referer: str
    first_seen_at: datetime
    last_seen_at: datetime


class DocumentShareVisitListRead(BaseModel):
    items: list[DocumentShareVisitRead]
    total: int
    page: int
    page_size: int


class PublicDocumentShareRead(BaseModel):
    title: str
    html: str
    cover_url: str
    cover_crop_235_1: str
    cover_crop_1_1: str
    revision: str
    expires_at: datetime
    asset_refresh_at: datetime


class PublicDocumentShareRevisionRead(BaseModel):
    revision: str
    expires_at: datetime


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
