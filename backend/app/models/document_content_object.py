from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class DocumentContentObject(Base):
    """Git-style immutable payload shared by document-version commits."""

    __tablename__ = "document_content_objects"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    storage_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    base_object_id: Mapped[int | None] = mapped_column(
        ID_TYPE,
        ForeignKey("document_content_objects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    delta_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    html_size: Mapped[int] = mapped_column(Integer, nullable=False)
