from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE


user_group_members = Table(
    "user_group_members",
    Base.metadata,
    Column("group_id", ID_TYPE, ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

model_user_access = Table(
    "model_user_access",
    Base.metadata,
    Column("model_id", ID_TYPE, ForeignKey("ai_models.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

model_group_access = Table(
    "model_group_access",
    Base.metadata,
    Column("model_id", ID_TYPE, ForeignKey("ai_models.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ID_TYPE, ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
)


class UserGroup(Base):
    __tablename__ = "user_groups"
    __table_args__ = (UniqueConstraint("name", name="uq_user_groups_name"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members = relationship("User", secondary=user_group_members, back_populates="groups")
    allowed_models = relationship("AIModel", secondary=model_group_access, back_populates="allowed_groups")
