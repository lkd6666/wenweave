from pydantic import BaseModel, ConfigDict, Field


class ChatImageLibraryReference(BaseModel):
    document_id: int = Field(gt=0)


class ChatImageLibraryBatchReference(ChatImageLibraryReference):
    asset_ids: list[str] = Field(min_length=1, max_length=100)


class ChatImageAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: int | None = None
    filename: str
    content_type: str
    size: int
    preview_url: str = ""
