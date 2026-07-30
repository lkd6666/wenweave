from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class OperationLogStatus(str, enum.Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationLog(Base):
    """Append-only business audit record.

    Resource and actor labels are stored as snapshots so that deleting the
    underlying user or object never makes a historical record ambiguous.
    """

    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("ix_operation_logs_created_status", "created_at", "status"),
        Index("ix_operation_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_operation_logs_action_created", "action", "created_at"),
        Index("ix_operation_logs_resource", "resource_type", "resource_id"),
        Index("ix_operation_logs_document_created", "document_id", "created_at"),
        Index("ix_operation_logs_client_ip_created", "client_ip", "created_at"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor_display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    resource_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    document_id: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True, index=True)
    session_id: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True, index=True)
    status: Mapped[OperationLogStatus] = mapped_column(
        Enum(OperationLogStatus, values_callable=lambda cls: [item.value for item in cls]),
        nullable=False,
        default=OperationLogStatus.SUCCEEDED,
        index=True,
    )
    summary: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    error_summary: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    details_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    client_ip: Mapped[str] = mapped_column(String(45), nullable=False, default="", index=True)
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
