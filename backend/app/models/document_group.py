from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE
from app.models.document_visibility import (
    VisibilityMode,
    document_group_visible_user_groups,
    document_group_visible_users,
)


class DocumentGroup(Base):
    __tablename__ = "document_groups"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_document_groups_owner_name"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_modified_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    visibility_mode: Mapped[VisibilityMode] = mapped_column(
        Enum(VisibilityMode, values_callable=lambda enum_class: [item.value for item in enum_class]),
        default=VisibilityMode.ALL,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    last_modified_by: Mapped["User | None"] = relationship("User", foreign_keys=[last_modified_by_id])
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="group")
    allowed_users: Mapped[List["User"]] = relationship("User", secondary=document_group_visible_users)
    allowed_groups: Mapped[List["UserGroup"]] = relationship("UserGroup", secondary=document_group_visible_user_groups)

    @property
    def allowed_user_ids(self) -> list[int]:
        return [user.id for user in self.allowed_users]

    @property
    def allowed_group_ids(self) -> list[int]:
        return [group.id for group in self.allowed_groups]

    @property
    def created_by(self) -> "User":
        return self.owner
