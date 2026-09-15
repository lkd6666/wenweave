from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_allow_password_change, require_admin
from app.core.security import hash_password, is_forced_password_change_value, verify_password
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.user import ChangePasswordRequest, UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def _admin_count(db: Session, exclude_user_id: int | None = None) -> int:
    query = db.query(User).filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


@router.get("", response_model=list[UserRead], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserRead, dependencies=[Depends(require_admin)])
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    user = User(
        username=payload.username,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        password_change_required=is_forced_password_change_value(payload.username, payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead, dependencies=[Depends(require_admin)])
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 保护措施：不能把系统里唯一的管理员降级或禁用，避免管理端被彻底锁死。
    demoting = (payload.role is not None and payload.role != UserRole.ADMIN) or payload.is_active is False
    if user.role == UserRole.ADMIN and demoting and _admin_count(db, exclude_user_id=user.id) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统必须保留至少一个启用状态的管理员账号")

    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.password:
        user.password_hash = hash_password(payload.password)
        user.password_change_required = is_forced_password_change_value(user.username, payload.password)
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_admin)],
)
def delete_user(user_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除当前登录账号")
    if user.role == UserRole.ADMIN and _admin_count(db, exclude_user_id=user.id) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统必须保留至少一个启用状态的管理员账号")

    db.delete(user)
    db.commit()


@router.post("/me/change-password", response_model=UserRead)
def change_my_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
) -> User:
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    if is_forced_password_change_value(current_user.username, payload.new_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能使用 123456、12345678 或与账号相同")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.password_change_required = False
    db.commit()
    db.refresh(current_user)
    return current_user
