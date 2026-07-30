from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SchemaMigration(Base):
    """A durable marker for the idempotent in-application schema revision."""

    __tablename__ = "schema_migrations"

    version: Mapped[str] = mapped_column(String(96), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
