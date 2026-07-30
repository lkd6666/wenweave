from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE


class ModelCallSource(str, enum.Enum):
    AGENT = "agent"
    AGENT_CONTEXT_COMPACTION = "agent_context_compaction"
    AGENT_RUNTIME_COMPACTION = "agent_runtime_compaction"
    THEME_GENERATION = "theme_generation"
    TEMPLATE_GENERATION = "template_generation"


class ModelCallStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModelCallRecord(Base):
    """Append-only accounting row for one request sent to a model provider."""

    __tablename__ = "model_call_records"
    __table_args__ = (
        Index("ix_model_call_records_model_started", "model_id", "started_at"),
        Index("ix_model_call_records_user_started", "user_id", "started_at"),
        Index("ix_model_call_records_source_started", "source", "started_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    # References intentionally remain logical IDs. Historical accounting must
    # survive model/provider cleanup; dashboard queries join live models to
    # enforce the current viewer's access rights.
    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(ID_TYPE, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True)
    source: Mapped[ModelCallSource] = mapped_column(
        Enum(ModelCallSource, values_callable=lambda values: [item.value for item in values]), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[ModelCallStatus] = mapped_column(
        Enum(ModelCallStatus, values_callable=lambda values: [item.value for item in values]), nullable=False
    )
    usage_reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
