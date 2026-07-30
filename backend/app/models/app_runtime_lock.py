from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppRuntimeLock(Base):
    """Stable rows used as portable cross-process `SELECT FOR UPDATE` locks."""

    __tablename__ = "app_runtime_locks"

    name: Mapped[str] = mapped_column(String(96), primary_key=True)
