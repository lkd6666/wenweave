from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole
from app.models.user_group import UserGroup
from app.schemas.document import DocumentGroupCreate, DocumentGroupRead, DocumentGroupUpdate
from app.services.document_access import accessible_document_groups_query, can_access_document_group
from app.services.document_activity import touch_document, touch_group

router = APIRouter(prefix="/api/document-groups", tags=["document-groups"])


def _get_accessible_group(db: Session, group_id: int, user: User) -> DocumentGroup:
    group = db.get(DocumentGroup, group_id)
    if not group or not can_access_document_group(user, group):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    return group


def _ensure_group_visibility_manager(group: DocumentGroup, user: User) -> None:
    if user.role != UserRole.ADMIN and group.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有分组创建人或管理员可以设置可见权限")


def _get_users(db: Session, user_ids: list[int]) -> list[User]:
    unique_ids = list(dict.fromkeys(user_ids))
    if not unique_ids:
        return []
    users = db.query(User).filter(User.id.in_(unique_ids)).all()
    if len(users) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户")
    users_by_id = {user.id: user for user in users}
    return [users_by_id[user_id] for user_id in unique_ids]


def _get_user_groups(db: Session, group_ids: list[int]) -> list[UserGroup]:
    unique_ids = list(dict.fromkeys(group_ids))
    if not unique_ids:
        return []
    groups = db.query(UserGroup).filter(UserGroup.id.in_(unique_ids)).all()
    if len(groups) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户组")
    groups_by_id = {group.id: group for group in groups}
    return [groups_by_id[group_id] for group_id in unique_ids]


def _apply_visibility(
    group: DocumentGroup,
    db: Session,
    visibility_mode: str,
    allowed_user_ids: list[int] | None,
    allowed_group_ids: list[int] | None,
) -> None:
    group.visibility_mode = VisibilityMode(visibility_mode)
    if group.visibility_mode == VisibilityMode.ALL:
        group.allowed_users = []
        group.allowed_groups = []
        return
    if allowed_user_ids is not None:
        group.allowed_users = _get_users(db, allowed_user_ids)
    if allowed_group_ids is not None:
        group.allowed_groups = _get_user_groups(db, allowed_group_ids)


def _normalized_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="分组名称不能为空")
    return normalized


def _ensure_name_available(db: Session, name: str, excluded_group_id: int | None = None) -> None:
    query = db.query(DocumentGroup).filter(DocumentGroup.name == name)
    if excluded_group_id is not None:
        query = query.filter(DocumentGroup.id != excluded_group_id)
    if query.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已存在同名分组")


@router.get("", response_model=list[DocumentGroupRead])
def list_groups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DocumentGroup]:
    return (
        accessible_document_groups_query(db.query(DocumentGroup), current_user)
        .options(
            selectinload(DocumentGroup.owner),
            selectinload(DocumentGroup.last_modified_by),
            selectinload(DocumentGroup.allowed_users),
            selectinload(DocumentGroup.allowed_groups),
        )
        .order_by(desc(DocumentGroup.updated_at), DocumentGroup.id)
        .all()
    )


@router.post("", response_model=DocumentGroupRead)
def create_group(
    payload: DocumentGroupCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentGroup:
    name = _normalized_name(payload.name)
    _ensure_name_available(db, name)
    group = DocumentGroup(
        owner_id=current_user.id,
        name=name,
        last_modified_by_id=current_user.id,
        visibility_mode=VisibilityMode(payload.visibility_mode),
    )
    _apply_visibility(group, db, payload.visibility_mode, payload.allowed_user_ids, payload.allowed_group_ids)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.patch("/{group_id}", response_model=DocumentGroupRead)
def update_group(
    group_id: int,
    payload: DocumentGroupUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentGroup:
    group = _get_accessible_group(db, group_id, current_user)
    changed = False
    if payload.name is not None:
        name = _normalized_name(payload.name)
        _ensure_name_available(db, name, group.id)
        if group.name != name:
            group.name = name
            changed = True
    visibility_fields = {"visibility_mode", "allowed_user_ids", "allowed_group_ids"}
    if visibility_fields.intersection(payload.model_fields_set):
        _ensure_group_visibility_manager(group, current_user)
        visibility_mode = payload.visibility_mode or group.visibility_mode.value
        _apply_visibility(group, db, visibility_mode, payload.allowed_user_ids, payload.allowed_group_ids)
        changed = True
    if changed:
        touch_group(group, current_user.id)
        db.commit()
        db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    group = _get_accessible_group(db, group_id, current_user)
    documents = db.query(Document).filter(Document.group_id == group.id).all()
    for document in documents:
        document.group_id = None
        touch_document(document, current_user.id)
    db.delete(group)
    db.commit()
