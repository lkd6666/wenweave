from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_BINARY


class AppBranding(Base):
    """Single global branding record used by the login page and app shell."""

    __tablename__ = "app_branding"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=False)
    system_name: Mapped[str] = mapped_column(String(120), nullable=False)
    logo_data: Mapped[bytes | None] = mapped_column(LONG_BINARY, nullable=True)
    logo_content_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    favicon_data: Mapped[bytes | None] = mapped_column(LONG_BINARY, nullable=True)
    favicon_content_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
