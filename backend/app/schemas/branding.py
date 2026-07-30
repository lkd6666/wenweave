from datetime import datetime

from pydantic import BaseModel, Field


class AppBrandingRead(BaseModel):
    system_name: str
    logo_url: str | None = None
    logo_content_type: str = ""
    favicon_url: str | None = None
    favicon_content_type: str = ""
    updated_at: datetime | None = None


class AppBrandingUpdate(BaseModel):
    system_name: str = Field(min_length=1, max_length=120)
