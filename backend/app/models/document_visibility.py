from __future__ import annotations

import enum

from sqlalchemy import Column, ForeignKey, Table

from app.db.base import Base
from app.db.types import ID_TYPE


class VisibilityMode(str, enum.Enum):
    ALL = "all"
    RESTRICTED = "restricted"


# 推文与分组分别保存直接授权用户及用户组。用户组成员关系变更后，权限查询会立即生效。
document_visible_users = Table(
    "document_visible_users",
    Base.metadata,
    Column("document_id", ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

document_visible_user_groups = Table(
    "document_visible_user_groups",
    Base.metadata,
    Column("document_id", ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("user_group_id", ID_TYPE, ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
)

document_group_visible_users = Table(
    "document_group_visible_users",
    Base.metadata,
    Column("document_group_id", ID_TYPE, ForeignKey("document_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

document_group_visible_user_groups = Table(
    "document_group_visible_user_groups",
    Base.metadata,
    Column("document_group_id", ID_TYPE, ForeignKey("document_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_group_id", ID_TYPE, ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
)
