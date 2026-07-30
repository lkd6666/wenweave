from pydantic import BaseModel, ConfigDict


class ChatImageAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size: int
    preview_url: str = ""
