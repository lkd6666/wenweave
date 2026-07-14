from pydantic import BaseModel, Field


class LayoutReferencePreviewRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class LayoutReferenceSummary(BaseModel):
    block_count: int
    image_slots: int
    extracted_from: str


class LayoutReferencePreview(BaseModel):
    reference_id: str
    canonical_url: str
    title: str
    site_name: str
    preview_html: str
    summary: LayoutReferenceSummary
    warning: str | None = None
