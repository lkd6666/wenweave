from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.user_group import UserGroup, user_group_members
from app.models.wechat_account import (
    WeChatAccount,
    WeChatDraft,
    wechat_account_group_access,
    wechat_account_user_access,
)
from app.schemas.wechat import (
    WeChatAccountCreate,
    WeChatAccountRead,
    WeChatAccountTestResult,
    WeChatAccountUpdate,
    WeChatAvailableAccountRead,
)
from app.services.wechat_official_account import WeChatApiError, WeChatOfficialAccountClient


router = APIRouter(prefix="/api/wechat-accounts", tags=["wechat-accounts"])


def _to_read(account: WeChatAccount) -> WeChatAccountRead:
    secret = decrypt_secret(account.app_secret_encrypted)
    return WeChatAccountRead(
        id=account.id,
        name=account.name,
        app_id=account.app_id,
        app_secret_masked=mask_secret(secret),
        allowed_user_ids=account.allowed_user_ids,
        allowed_group_ids=account.allowed_group_ids,
        is_active=account.is_active,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _find_account(db: Session, account_id: int) -> WeChatAccount:
    account = db.get(WeChatAccount, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公众号账号不存在")
    return account


def _find_users(db: Session, user_ids: list[int]) -> list[User]:
    unique_ids = list(dict.fromkeys(user_ids))
    if not unique_ids:
        return []
    users = db.query(User).filter(User.id.in_(unique_ids)).all()
    if len(users) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户")
    return users


def _find_groups(db: Session, group_ids: list[int]) -> list[UserGroup]:
    unique_ids = list(dict.fromkeys(group_ids))
    if not unique_ids:
        return []
    groups = db.query(UserGroup).filter(UserGroup.id.in_(unique_ids)).all()
    if len(groups) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户组")
    groups_by_id = {group.id: group for group in groups}
    return [groups_by_id[group_id] for group_id in unique_ids]


@router.get("/available", response_model=list[WeChatAvailableAccountRead])
def list_available_accounts(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[WeChatAccount]:
    query = db.query(WeChatAccount).filter(WeChatAccount.is_active.is_(True))
    if current_user.role != UserRole.ADMIN:
        query = (
            query.outerjoin(
                wechat_account_user_access,
                WeChatAccount.id == wechat_account_user_access.c.account_id,
            )
            .outerjoin(
                wechat_account_group_access,
                WeChatAccount.id == wechat_account_group_access.c.account_id,
            )
            .outerjoin(
                user_group_members,
                wechat_account_group_access.c.group_id == user_group_members.c.group_id,
            )
            .filter(
                or_(
                    wechat_account_user_access.c.user_id == current_user.id,
                    user_group_members.c.user_id == current_user.id,
                )
            )
            .distinct()
        )
    return query.order_by(WeChatAccount.name, WeChatAccount.id).all()


@router.get("", response_model=list[WeChatAccountRead], dependencies=[Depends(require_admin)])
def list_accounts(db: Session = Depends(get_db)) -> list[WeChatAccountRead]:
    accounts = db.query(WeChatAccount).order_by(WeChatAccount.id).all()
    return [_to_read(account) for account in accounts]


@router.post("", response_model=WeChatAccountRead, dependencies=[Depends(require_admin)])
def create_account(payload: WeChatAccountCreate, db: Session = Depends(get_db)) -> WeChatAccountRead:
    account = WeChatAccount(
        name=payload.name,
        app_id=payload.app_id,
        app_secret_encrypted=encrypt_secret(payload.app_secret),
        is_active=payload.is_active,
    )
    account.allowed_users = _find_users(db, payload.allowed_user_ids)
    account.allowed_groups = _find_groups(db, payload.allowed_group_ids)
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AppID 已被配置") from exc
    db.refresh(account)
    return _to_read(account)


@router.patch("/{account_id}", response_model=WeChatAccountRead, dependencies=[Depends(require_admin)])
def update_account(account_id: int, payload: WeChatAccountUpdate, db: Session = Depends(get_db)) -> WeChatAccountRead:
    account = _find_account(db, account_id)
    if payload.name is not None:
        account.name = payload.name
    if payload.app_id is not None:
        account.app_id = payload.app_id
    if payload.app_secret:
        account.app_secret_encrypted = encrypt_secret(payload.app_secret)
    if payload.is_active is not None:
        account.is_active = payload.is_active
    if payload.allowed_user_ids is not None:
        account.allowed_users = _find_users(db, payload.allowed_user_ids)
    if payload.allowed_group_ids is not None:
        account.allowed_groups = _find_groups(db, payload.allowed_group_ids)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AppID 已被配置") from exc
    db.refresh(account)
    return _to_read(account)


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_admin)],
)
def delete_account(account_id: int, db: Session = Depends(get_db)) -> None:
    account = _find_account(db, account_id)
    if db.query(WeChatDraft).filter(WeChatDraft.account_id == account.id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已有草稿记录的账号不能删除，请停用该账号")
    db.delete(account)
    db.commit()


@router.post("/{account_id}/test", response_model=WeChatAccountTestResult, dependencies=[Depends(require_admin)])
async def test_account(account_id: int, db: Session = Depends(get_db)) -> WeChatAccountTestResult:
    account = _find_account(db, account_id)
    try:
        await WeChatOfficialAccountClient().test_account(account)
    except WeChatApiError as exc:
        detail = str(exc)
        if exc.code == 40164:
            detail = f"{detail}。请将部署服务器的公网出口 IP 加入公众号后台 API IP 白名单"
        return WeChatAccountTestResult(success=False, message=detail)
    return WeChatAccountTestResult(success=True, message="连接成功：已取得微信接口调用凭据")
