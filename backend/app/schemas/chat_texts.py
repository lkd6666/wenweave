from pydantic import BaseModel, ConfigDict


class ChatTextAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    document_id: int
    session_id: int
    message_id: int | None = None
    filename: str
    size: int
    characters: int
    lines: int
    sha256: str
