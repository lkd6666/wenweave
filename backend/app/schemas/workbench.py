from pydantic import BaseModel

from app.schemas.document import DocumentGroupRead, DocumentSummary


class DocumentPageRead(BaseModel):
    items: list[DocumentSummary]
    total: int
    page: int
    page_size: int


class WorkbenchDocumentSummary(DocumentSummary):
    group_name: str | None = None


class WorkbenchDocumentPageRead(BaseModel):
    items: list[WorkbenchDocumentSummary]
    total: int
    page: int
    page_size: int


class WorkbenchGroupItemRead(BaseModel):
    group: DocumentGroupRead
    document_total: int
    documents: DocumentPageRead


class WorkbenchGroupPageRead(BaseModel):
    items: list[WorkbenchGroupItemRead]
    total: int
    page: int
    page_size: int


class WorkbenchGroupedRead(BaseModel):
    groups: WorkbenchGroupPageRead
    ungrouped: DocumentPageRead
