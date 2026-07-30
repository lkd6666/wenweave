from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.models.user_group import UserGroup
from app.schemas.user_group import UserGroupCreate, UserGroupRead, UserGroupUpdate

router = APIRouter(prefix="/api/user-groups", tags=["user-groups"], dependencies=[Depends(require_admin)])


def _get_users(db: Session, user_ids: list[int]) -> list[User]:
    unique_ids = list(dict.fromkeys(user_ids))
    if not unique_ids:
        return []
    users = db.query(User).filter(User.id.in_(unique_ids)).all()
    if len(users) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的用户")
    users_by_id = {user.id: user for user in users}
    return [users_by_id[user_id] for user_id in unique_ids]


@router.get("", response_model=list[UserGroupRead])
def list_user_groups(db: Session = Depends(get_db)) -> list[UserGroup]:
    return db.query(UserGroup).order_by(UserGroup.id).all()


@router.post("", response_model=UserGroupRead)
def create_user_group(payload: UserGroupCreate, db: Session = Depends(get_db)) -> UserGroup:
    name = payload.name.strip()
    if db.query(UserGroup).filter(UserGroup.name == name).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户组名称已存在")
    group = UserGroup(name=name, members=_get_users(db, payload.user_ids))
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.patch("/{group_id}", response_model=UserGroupRead)
def update_user_group(group_id: int, payload: UserGroupUpdate, db: Session = Depends(get_db)) -> UserGroup:
    group = db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    if payload.name is not None:
        name = payload.name.strip()
        duplicate = db.query(UserGroup).filter(UserGroup.name == name, UserGroup.id != group.id).first()
        if duplicate:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户组名称已存在")
        group.name = name
    if payload.user_ids is not None:
        group.members = _get_users(db, payload.user_ids)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_user_group(group_id: int, db: Session = Depends(get_db)) -> None:
    group = db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    db.delete(group)
    db.commit()
