from pydantic import BaseModel, Field


class LayoutReferencePreviewRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


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
