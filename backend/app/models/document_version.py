from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class DocumentVersionSource(str, enum.Enum):
    INITIAL = "initial"
    MANUAL = "manual"
    AI = "ai"
    RESTORE = "restore"


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_document_number"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    # Retained for migration compatibility. New commits store their immutable
    # content in DocumentContentObject and leave this legacy column empty.
    html: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    content_object_id: Mapped[int | None] = mapped_column(
        ID_TYPE,
        ForeignKey("document_content_objects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[DocumentVersionSource] = mapped_column(Enum(DocumentVersionSource), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    created_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship("Document", back_populates="versions")
    content_object: Mapped["DocumentContentObject | None"] = relationship(
        "DocumentContentObject", foreign_keys=[content_object_id]
    )
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
