from __future__ import annotations

from sqlalchemy import false, or_
from sqlalchemy.orm import Query

from app.models.ai_model import AIModel
from app.models.ai_image_model import AIImageModel
from app.models.user import User, UserRole
from app.models.user_group import UserGroup


def can_access_model(user: User, model: AIModel) -> bool:
    """管理员始终可用；受限模型对直接授权或用户组授权采用并集规则。"""
    if user.role == UserRole.ADMIN or model.access_mode != "restricted":
        return True
    if any(allowed_user.id == user.id for allowed_user in model.allowed_users):
        return True
    user_group_ids = {group.id for group in user.groups}
    return any(group.id in user_group_ids for group in model.allowed_groups)


def accessible_models_query(query: Query, user: User) -> Query:
    if user.role == UserRole.ADMIN:
        return query

    conditions = [
        AIModel.access_mode == "all",
        AIModel.allowed_users.any(User.id == user.id),
    ]
    group_ids = [group.id for group in user.groups]
    if group_ids:
        conditions.append(AIModel.allowed_groups.any(UserGroup.id.in_(group_ids)))
    else:
        conditions.append(false())
    return query.filter(or_(*conditions))


def can_access_image_model(user: User, model: AIImageModel) -> bool:
    if user.role == UserRole.ADMIN or model.access_mode != "restricted":
        return True
    if any(allowed_user.id == user.id for allowed_user in model.allowed_users):
        return True
    user_group_ids = {group.id for group in user.groups}
    return any(group.id in user_group_ids for group in model.allowed_groups)


def accessible_image_models_query(query: Query, user: User) -> Query:
    if user.role == UserRole.ADMIN:
        return query
    conditions = [
        AIImageModel.access_mode == "all",
        AIImageModel.allowed_users.any(User.id == user.id),
    ]
    group_ids = [group.id for group in user.groups]
    if group_ids:
        conditions.append(AIImageModel.allowed_groups.any(UserGroup.id.in_(group_ids)))
    else:
        conditions.append(false())
    return query.filter(or_(*conditions))
