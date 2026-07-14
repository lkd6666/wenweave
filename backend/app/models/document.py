from __future__ import annotations

import enum
from datetime import datetime
from typing import List

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT
from app.models.document_visibility import (
    VisibilityMode,
    document_visible_user_groups,
    document_visible_users,
)


class DocumentSourceType(str, enum.Enum):
    BLANK = "blank"
    PDF = "pdf"
    WORD = "word"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("document_groups.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_modified_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="未命名排版")
    current_html: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    source_type: Mapped[DocumentSourceType] = mapped_column(
        Enum(DocumentSourceType), default=DocumentSourceType.BLANK, nullable=False
    )
    source_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_size: Mapped[int | None] = mapped_column(nullable=True)
    visibility_mode: Mapped[VisibilityMode] = mapped_column(
        Enum(VisibilityMode, values_callable=lambda enum_class: [item.value for item in enum_class]),
        default=VisibilityMode.ALL,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="document", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )
    versions: Mapped[List["DocumentVersion"]] = relationship(
        "DocumentVersion", back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.version_number"
    )
    group: Mapped["DocumentGroup | None"] = relationship("DocumentGroup", back_populates="documents")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    last_modified_by: Mapped["User | None"] = relationship("User", foreign_keys=[last_modified_by_id])
    allowed_users: Mapped[List["User"]] = relationship("User", secondary=document_visible_users)
    allowed_groups: Mapped[List["UserGroup"]] = relationship("UserGroup", secondary=document_visible_user_groups)

    @property
    def allowed_user_ids(self) -> list[int]:
        return [user.id for user in self.allowed_users]

    @property
    def allowed_group_ids(self) -> list[int]:
        return [group.id for group in self.allowed_groups]

    @property
    def has_source_file(self) -> bool:
        return bool(self.source_object_key and self.source_filename and self.source_content_type and self.source_size)
