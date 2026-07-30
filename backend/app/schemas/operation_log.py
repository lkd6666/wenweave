from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.operation_log import OperationLogStatus


class OperationLogRead(BaseModel):
    id: int
    actor_user_id: int | None
    actor_username: str
    actor_display_name: str
    action: str
    resource_type: str
    resource_id: str
    resource_name: str
    document_id: int | None
    session_id: int | None
    status: OperationLogStatus
    summary: str
    error_summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str
    client_ip: str
    user_agent: str
    created_at: datetime


class OperationLogListRead(BaseModel):
    items: list[OperationLogRead]
    total: int
    page: int
    page_size: int
