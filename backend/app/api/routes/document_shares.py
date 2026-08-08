from __future__ import annotations

from datetime import datetime, timezone
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.document import Document
from app.models.document_share import DocumentShare, DocumentShareVisit
from app.models.user import User
from app.schemas.document import (
    DocumentShareCreate,
    DocumentShareRead,
    DocumentShareUpdate,
    DocumentShareVisitListRead,
    DocumentShareVisitRead,
    PublicDocumentShareRead,
    PublicDocumentShareRevisionRead,
)
from app.services.document_access import can_access_document
from app.services.document_shares import (
    ShareUnavailableError,
    VISITOR_SESSION_TTL,
    as_utc,
    create_share,
    document_revision,
    is_share_active,
    public_document_cover_url,
    public_document_html,
    record_public_visit,
    resolve_public_share,
    revoke_share,
    share_token,
    utcnow,
    visitor_cookie_name,
)


router = APIRouter(prefix="/api/documents", tags=["document-shares"])
public_router = APIRouter(prefix="/api/public/shares", tags=["public-document-shares"])


def _get_accessible_document(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if not document or not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return document


def _get_managed_share(db: Session, document: Document, share_id: int) -> DocumentShare:
    share = db.query(DocumentShare).filter(DocumentShare.id == share_id, DocumentShare.document_id == document.id).first()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享链接不存在")
    return share


def _to_share_read(db: Session, share: DocumentShare) -> DocumentShareRead:
    visit_count, last_visited_at = (
        db.query(func.count(DocumentShareVisit.id), func.max(DocumentShareVisit.last_seen_at))
        .filter(DocumentShareVisit.share_id == share.id)
        .one()
    )
    return DocumentShareRead(
        id=share.id,
        document_id=share.document_id,
        # The stored title is retained for a deleted document, but active shares
        # must always reflect the document's latest title.
        document_title=share.document.title if share.document is not None else share.document_title,
        token=share_token(share),
        created_by_id=share.created_by_id,
        created_by_username=share.created_by_username,
        created_by_display_name=share.created_by_display_name,
        expires_at=as_utc(share.expires_at),
        revoked_at=as_utc(share.revoked_at) if share.revoked_at else None,
        revoked_by_id=share.revoked_by_id,
        revoked_by_username=share.revoked_by_username,
        revoked_by_display_name=share.revoked_by_display_name,
        created_at=as_utc(share.created_at),
        is_active=is_share_active(share),
        visit_count=int(visit_count or 0),
        last_visited_at=as_utc(last_visited_at) if last_visited_at else None,
    )


@router.get("/{document_id}/shares", response_model=list[DocumentShareRead])
def list_document_shares(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentShareRead]:
    document = _get_accessible_document(db, document_id, current_user)
    shares = (
        db.query(DocumentShare)
        .filter(DocumentShare.document_id == document.id)
        .order_by(DocumentShare.created_at.desc(), DocumentShare.id.desc())
        .all()
    )
    return [_to_share_read(db, share) for share in shares]


@router.post("/{document_id}/shares", response_model=DocumentShareRead, status_code=status.HTTP_201_CREATED)
def create_document_share(
    document_id: int,
    payload: DocumentShareCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentShareRead:
    document = _get_accessible_document(db, document_id, current_user)
    share, _ = create_share(db, document, current_user, payload.expires_at)
    db.commit()
    db.refresh(share)
    return _to_share_read(db, share)


@router.patch("/{document_id}/shares/{share_id}", response_model=DocumentShareRead)
def update_document_share(
    document_id: int,
    share_id: int,
    payload: DocumentShareUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentShareRead:
    document = _get_accessible_document(db, document_id, current_user)
    share = _get_managed_share(db, document, share_id)
    if not is_share_active(share):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已过期或停用的分享链接不能修改")
    expires_at = payload.expires_at.replace(tzinfo=timezone.utc) if payload.expires_at.tzinfo is None else payload.expires_at.astimezone(timezone.utc)
    if expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="分享有效期必须晚于当前时间")
    share.expires_at = expires_at
    db.commit()
    db.refresh(share)
    return _to_share_read(db, share)


@router.post("/{document_id}/shares/{share_id}/revoke", response_model=DocumentShareRead)
def revoke_document_share(
    document_id: int,
    share_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentShareRead:
    document = _get_accessible_document(db, document_id, current_user)
    share = _get_managed_share(db, document, share_id)
    revoke_share(share, current_user)
    db.commit()
    db.refresh(share)
    return _to_share_read(db, share)


@router.get("/{document_id}/shares/{share_id}/visits", response_model=DocumentShareVisitListRead)
def list_document_share_visits(
    document_id: int,
    share_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentShareVisitListRead:
    document = _get_accessible_document(db, document_id, current_user)
    share = _get_managed_share(db, document, share_id)
    query = db.query(DocumentShareVisit).filter(DocumentShareVisit.share_id == share.id)
    total = query.count()
    visits = (
        query.order_by(DocumentShareVisit.first_seen_at.desc(), DocumentShareVisit.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return DocumentShareVisitListRead(
        items=[
            DocumentShareVisitRead(
                id=item.id,
                ip_address=item.ip_address,
                user_agent=item.user_agent,
                referer=item.referer,
                first_seen_at=as_utc(item.first_seen_at),
                last_seen_at=as_utc(item.last_seen_at),
            )
            for item in visits
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def _public_share_or_gone(db: Session, token: str) -> DocumentShare:
    try:
        return resolve_public_share(db, token)
    except ShareUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="分享链接已失效") from exc


@public_router.get("/{token}", response_model=PublicDocumentShareRead)
def get_public_document_share(
    token: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> PublicDocumentShareRead:
    share = _public_share_or_gone(db, token)
    document = share.document
    if document is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="分享链接已失效")
    cookie_name = visitor_cookie_name(share)
    visitor_session = request.cookies.get(cookie_name, "")
    if not visitor_session or len(visitor_session) > 256:
        visitor_session = token_urlsafe(24)
    record_public_visit(db, share, request, visitor_session)
    html, asset_refresh_at = public_document_html(db, share)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.set_cookie(
        key=cookie_name,
        value=visitor_session,
        max_age=int(VISITOR_SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path=f"/api/public/shares/{token}",
    )
    return PublicDocumentShareRead(
        title=document.title,
        html=html,
        cover_url=public_document_cover_url(db, share),
        cover_crop_235_1=document.wechat_pic_crop_235_1,
        cover_crop_1_1=document.wechat_pic_crop_1_1,
        revision=document_revision(document),
        expires_at=as_utc(share.expires_at),
        asset_refresh_at=asset_refresh_at,
    )


@public_router.get("/{token}/revision", response_model=PublicDocumentShareRevisionRead)
def get_public_document_share_revision(token: str, response: Response, db: Session = Depends(get_db)) -> PublicDocumentShareRevisionRead:
    share = _public_share_or_gone(db, token)
    document = share.document
    if document is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="分享链接已失效")
    response.headers["Cache-Control"] = "no-store, private"
    return PublicDocumentShareRevisionRead(revision=document_revision(document), expires_at=as_utc(share.expires_at))
