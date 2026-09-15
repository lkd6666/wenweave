from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, String, Table, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE, MEDIUM_TEXT

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User
    from app.models.user_group import UserGroup


wechat_account_user_access = Table(
    "wechat_account_user_access",
    Base.metadata,
    Column("account_id", ID_TYPE, ForeignKey("wechat_accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

wechat_account_group_access = Table(
    "wechat_account_group_access",
    Base.metadata,
    Column("account_id", ID_TYPE, ForeignKey("wechat_accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ID_TYPE, ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
)


class WeChatDraftStatus(str, enum.Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WeChatDraftSyncMode(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"


class WeChatAccount(Base):
    __tablename__ = "wechat_accounts"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    app_secret_encrypted: Mapped[str] = mapped_column(MEDIUM_TEXT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    allowed_users: Mapped[list["User"]] = relationship(
        "User", secondary=wechat_account_user_access, lazy="selectin"
    )
    allowed_groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup", secondary=wechat_account_group_access, lazy="selectin"
    )
    drafts: Mapped[list["WeChatDraft"]] = relationship(back_populates="account")
    cover_materials: Mapped[list["WeChatCoverMaterial"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    body_image_materials: Mapped[list["WeChatBodyImageMaterial"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    @property
    def allowed_user_ids(self) -> list[int]:
        return [user.id for user in self.allowed_users]

    @property
    def allowed_group_ids(self) -> list[int]:
        return [group.id for group in self.allowed_groups]


class WeChatDraft(Base):
    __tablename__ = "wechat_drafts"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("wechat_accounts.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[WeChatDraftStatus] = mapped_column(
        Enum(WeChatDraftStatus, values_callable=lambda values: [item.value for item in values]), nullable=False
    )
    sync_mode: Mapped[WeChatDraftSyncMode] = mapped_column(
        Enum(WeChatDraftSyncMode, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=WeChatDraftSyncMode.CREATE,
    )
    media_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    article_title: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_code: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account: Mapped[WeChatAccount] = relationship(back_populates="drafts")
    document: Mapped["Document"] = relationship("Document", back_populates="wechat_drafts")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])


class WeChatCoverMaterial(Base):
    __tablename__ = "wechat_cover_materials"
    __table_args__ = (UniqueConstraint("account_id", "content_sha256", name="uq_wechat_cover_material_hash"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("wechat_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_id: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account: Mapped[WeChatAccount] = relationship(back_populates="cover_materials")


class WeChatBodyImageMaterial(Base):
    __tablename__ = "wechat_body_image_materials"
    __table_args__ = (
        UniqueConstraint("account_id", "source_url_sha256", name="uq_wechat_body_image_source_hash"),
        Index("ix_wechat_body_image_account_content_hash", "account_id", "content_sha256"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("wechat_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_url_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    wechat_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    upload_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped[WeChatAccount] = relationship(back_populates="body_image_materials")
