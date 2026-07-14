from __future__ import annotations

from sqlalchemy import and_, false, or_
from sqlalchemy.orm import Query

from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole
from app.models.user_group import UserGroup


def _visibility_conditions(resource: type[Document] | type[DocumentGroup], user: User):
    group_ids = [group.id for group in user.groups]
    conditions = [
        resource.visibility_mode == VisibilityMode.ALL,
        resource.allowed_users.any(User.id == user.id),
    ]
    conditions.append(resource.allowed_groups.any(UserGroup.id.in_(group_ids)) if group_ids else false())
    return conditions


def can_access_document_group(user: User, group: DocumentGroup) -> bool:
    if user.role == UserRole.ADMIN or group.visibility_mode == VisibilityMode.ALL:
        return True
    if any(allowed_user.id == user.id for allowed_user in group.allowed_users):
        return True
    user_group_ids = {item.id for item in user.groups}
    return any(item.id in user_group_ids for item in group.allowed_groups)


def can_access_document(user: User, document: Document) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if document.visibility_mode == VisibilityMode.RESTRICTED:
        is_directly_allowed = any(allowed_user.id == user.id for allowed_user in document.allowed_users)
        user_group_ids = {item.id for item in user.groups}
        is_group_allowed = any(item.id in user_group_ids for item in document.allowed_groups)
        if not is_directly_allowed and not is_group_allowed:
            return False
    return document.group is None or can_access_document_group(user, document.group)


def accessible_document_groups_query(query: Query, user: User) -> Query:
    if user.role == UserRole.ADMIN:
        return query
    return query.filter(or_(*_visibility_conditions(DocumentGroup, user)))


def accessible_documents_query(query: Query, user: User) -> Query:
    if user.role == UserRole.ADMIN:
        return query
    document_visible = or_(*_visibility_conditions(Document, user))
    group_visible = or_(
        Document.group_id.is_(None),
        Document.group.has(or_(*_visibility_conditions(DocumentGroup, user))),
    )
    return query.filter(and_(document_visible, group_visible))
