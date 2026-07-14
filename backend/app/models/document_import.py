from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE
from app.models.document import DocumentSourceType


class DocumentImportStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"


class DocumentImport(Base):
    """A short-lived, user-scoped authorization envelope for direct OSS imports."""

    __tablename__ = "document_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[DocumentSourceType] = mapped_column(
        Enum(DocumentSourceType), nullable=False
    )
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # utf8mb4 unique indexes are limited to 3072 bytes on common MySQL/InnoDB deployments.
    # 768 characters keeps the object key safely indexable while exceeding generated OSS key needs.
    source_object_key: Mapped[str] = mapped_column(String(768), nullable=False, unique=True)
    status: Mapped[DocumentImportStatus] = mapped_column(
        Enum(DocumentImportStatus), nullable=False, default=DocumentImportStatus.PENDING
    )
    document_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assets: Mapped[list["DocumentImportAsset"]] = relationship(
        "DocumentImportAsset", back_populates="import_session", cascade="all, delete-orphan"
    )


class DocumentImportAsset(Base):
    __tablename__ = "document_import_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    import_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(768), nullable=False, unique=True)

    import_session: Mapped[DocumentImport] = relationship("DocumentImport", back_populates="assets")
