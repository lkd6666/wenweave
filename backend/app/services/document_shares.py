from __future__ import annotations

import hashlib
import ipaddress
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.document import Document
from app.models.document_share import DocumentShare, DocumentShareVisit
from app.models.storage_config import StorageConfig
from app.models.user import User
from app.services import oss_client


VISITOR_SESSION_TTL = timedelta(minutes=30)


class ShareUnavailableError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def document_revision(document: Document) -> str:
    material = "\0".join(
        (
            document.title,
            document.current_html,
            document.wechat_cover_url,
            document.wechat_pic_crop_235_1,
            document.wechat_pic_crop_1_1,
        )
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def is_share_active(share: DocumentShare, now: datetime | None = None) -> bool:
    current = now or utcnow()
    return share.document_id is not None and share.revoked_at is None and as_utc(share.expires_at) > current


def create_share(db: Session, document: Document, actor: User, expires_at: datetime) -> tuple[DocumentShare, str]:
    expiry = as_utc(expires_at)
    if expiry <= utcnow():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="分享有效期必须晚于当前时间")
    raw_token = token_urlsafe(32)
    share = DocumentShare(
        document_id=document.id,
        document_title=document.title,
        token_hash=token_hash(raw_token),
        token_encrypted=encrypt_secret(raw_token),
        created_by_id=actor.id,
        created_by_username=actor.username,
        created_by_display_name=actor.display_name,
        expires_at=expiry,
    )
    db.add(share)
    db.flush()
    return share, raw_token


def share_token(share: DocumentShare) -> str:
    try:
        return decrypt_secret(share.token_encrypted)
    except Exception:  # noqa: BLE001 - historical metadata remains manageable even if a key was lost.
        return ""


def resolve_public_share(db: Session, raw_token: str) -> DocumentShare:
    if not raw_token or len(raw_token) > 512:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享链接不存在")
    share = db.query(DocumentShare).filter(DocumentShare.token_hash == token_hash(raw_token)).first()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享链接不存在")
    if not is_share_active(share):
        raise ShareUnavailableError()
    return share


def revoke_share(share: DocumentShare, actor: User, now: datetime | None = None) -> bool:
    if share.revoked_at is not None:
        return False
    share.revoked_at = now or utcnow()
    share.revoked_by_id = actor.id
    share.revoked_by_username = actor.username
    share.revoked_by_display_name = actor.display_name
    return True


def revoke_document_shares(db: Session, document: Document, actor: User) -> int:
    active_shares = (
        db.query(DocumentShare)
        .filter(DocumentShare.document_id == document.id, DocumentShare.revoked_at.is_(None))
        .all()
    )
    for share in active_shares:
        revoke_share(share, actor)
        share.document_id = None
    return len(active_shares)


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks = []
    for raw_network in get_settings().trusted_proxy_cidrs_list:
        try:
            networks.append(ipaddress.ip_network(raw_network, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def request_ip_address(request: Request) -> str:
    peer = request.client.host if request.client else ""
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer[:45]
    if not any(peer_address in network for network in _trusted_proxy_networks()):
        return str(peer_address)
    for candidate in request.headers.get("x-forwarded-for", "").split(","):
        try:
            return str(ipaddress.ip_address(candidate.strip()))
        except ValueError:
            continue
    return str(peer_address)


def visitor_cookie_name(share: DocumentShare) -> str:
    return f"document_share_visit_{share.token_hash[:20]}"


def record_public_visit(db: Session, share: DocumentShare, request: Request, visitor_session: str) -> None:
    session_hash = token_hash(visitor_session)
    now = utcnow()
    visit = (
        db.query(DocumentShareVisit)
        .filter(
            DocumentShareVisit.share_id == share.id,
            DocumentShareVisit.visitor_session_hash == session_hash,
        )
        .first()
    )
    if visit is None:
        visit = DocumentShareVisit(
            share_id=share.id,
            visitor_session_hash=session_hash,
            ip_address=request_ip_address(request),
            user_agent=request.headers.get("user-agent", "")[:1024],
            referer=request.headers.get("referer", "")[:2048],
            last_seen_at=now,
        )
        db.add(visit)
    else:
        visit.last_seen_at = now
    db.commit()


def _configured_storage(db: Session) -> StorageConfig | None:
    storage = db.query(StorageConfig).first()
    if not storage or not storage.endpoint or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        return None
    return storage


def public_document_html(db: Session, share: DocumentShare) -> tuple[str, datetime]:
    document = share.document
    if document is None:
        raise ShareUnavailableError()
    remaining_seconds = max(1, int((as_utc(share.expires_at) - utcnow()).total_seconds()))
    expires_in = min(remaining_seconds, get_settings().DOCUMENT_SHARE_IMAGE_URL_EXPIRE_SECONDS)
    storage = _configured_storage(db)
    if storage is None:
        return document.current_html, utcnow() + timedelta(seconds=expires_in)
    try:
        rendered, _ = oss_client.refresh_document_image_urls(storage, [document.current_html], expires=expires_in)
        return rendered[0], utcnow() + timedelta(seconds=expires_in)
    except Exception:  # noqa: BLE001 - an image signing failure must not hide readable article text.
        return document.current_html, utcnow() + timedelta(seconds=expires_in)


def public_document_cover_url(db: Session, share: DocumentShare) -> str:
    document = share.document
    if document is None:
        raise ShareUnavailableError()
    cover_url = document.wechat_cover_url.strip()
    if not cover_url:
        return ""
    remaining_seconds = max(1, int((as_utc(share.expires_at) - utcnow()).total_seconds()))
    expires_in = min(remaining_seconds, get_settings().DOCUMENT_SHARE_IMAGE_URL_EXPIRE_SECONDS)
    storage = _configured_storage(db)
    if storage is None:
        return cover_url
    try:
        return oss_client.refresh_document_image_url(storage, cover_url, expires=expires_in)
    except Exception:  # noqa: BLE001 - a stale cover should not prevent the article from loading.
        return cover_url
