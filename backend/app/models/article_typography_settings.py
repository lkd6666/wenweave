from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE


class ArticleTypographySettings(Base):
    """The single, administrator-managed default for article body typography."""

    __tablename__ = "article_typography_settings"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=False)
    horizontal_padding_px: Mapped[float] = mapped_column(Float, nullable=False, default=4)
    paragraph_spacing_px: Mapped[float] = mapped_column(Float, nullable=False, default=20)
    font_size_px: Mapped[float] = mapped_column(Float, nullable=False, default=15)
    line_height_em: Mapped[float] = mapped_column(Float, nullable=False, default=2)
    letter_spacing_px: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    text_indent_em: Mapped[float] = mapped_column(Float, nullable=False, default=2)
    text_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#000000")
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
