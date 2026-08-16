import logging

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.browser_capture_upload import BrowserCaptureUploadError, read_browser_capture_upload
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.layout_reference import (
    LayoutCaptureSessionRead,
    LayoutReferencePreview,
    LayoutReferencePreviewRequest,
)
from app.services.layout_reference import (
    LayoutReferenceExpiredError,
    LayoutReferenceError,
    WechatVerificationRequiredError,
    complete_layout_capture_session,
    create_layout_capture_session,
    create_layout_reference,
    get_layout_reference_preview_asset,
)
from app.services.operation_logs import set_request_audit_actor

router = APIRouter(prefix="/api/layout-references", tags=["layout-references"])
logger = logging.getLogger(__name__)


@router.post("/preview", response_model=LayoutReferencePreview)
async def preview_layout_reference(
    payload: LayoutReferencePreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        reference = await create_layout_reference(payload.url, current_user.id, db)
        db.commit()
        return reference.preview_payload()
    except WechatVerificationRequiredError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "wechat_verification_required",
                "message": str(exc),
                "url": exc.canonical_url,
            },
        ) from exc
    except LayoutReferenceError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("解析排版参考失败", exc_info=exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="参考页面解析失败，请稍后重试或更换公开文章链接") from exc


@router.post("/capture-sessions", response_model=LayoutCaptureSessionRead, status_code=status.HTTP_201_CREATED)
def start_layout_capture_session(
    payload: LayoutReferencePreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        capture_session, token = create_layout_capture_session(payload.url, current_user.id, db)
        db.commit()
        return {
            "id": capture_session.id,
            "token": token,
            "canonical_url": capture_session.canonical_url,
            "expires_at": capture_session.expires_at,
            "purpose": capture_session.purpose,
        }
    except LayoutReferenceError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/capture-sessions/{capture_id}/complete", response_model=LayoutReferencePreview)
async def complete_browser_layout_capture(
    capture_id: str,
    request: Request,
    source_html: str = Form(..., min_length=1),
    title: str = Form(default="", max_length=200),
    manifest: str = Form(..., min_length=2),
    files: list[UploadFile] = File(default=[]),
    capture_token: str = Header(..., alias="X-Layout-Capture-Token", min_length=20, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    try:
        capture_manifest, captured_assets = await read_browser_capture_upload(manifest, files)
        if capture_manifest.cover_asset_id is not None:
            raise LayoutReferenceError("排版参考采集不接受独立封面素材")

        reference = complete_layout_capture_session(
            db,
            capture_id,
            capture_token,
            capture_manifest.url,
            source_html,
            title,
            captured_assets,
            capture_manifest.omitted_asset_count,
        )
        actor = db.get(User, reference.user_id)
        if actor is not None:
            set_request_audit_actor(request, actor)
        db.commit()
        return reference.preview_payload()
    except BrowserCaptureUploadError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LayoutReferenceExpiredError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except LayoutReferenceError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("浏览器采集排版参考失败", exc_info=exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="浏览器采集处理失败，请重新发起抓取") from exc
    finally:
        for file in files:
            await file.close()


@router.get("/{reference_id}/assets/{asset_id}")
def preview_layout_reference_asset(
    reference_id: str,
    asset_id: str,
    preview_token: str = Query(min_length=20, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    """Serve a temporary asset through an unguessable, short-lived preview URL."""
    try:
        asset = get_layout_reference_preview_asset(db, reference_id, asset_id, preview_token)
    except LayoutReferenceError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="参考图片已过期或不可用") from None
    if asset.data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="参考图片已过期或不可用")
    return Response(
        content=asset.data,
        media_type=asset.content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )
