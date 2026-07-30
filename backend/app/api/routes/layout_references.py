import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.layout_reference import LayoutReferencePreview, LayoutReferencePreviewRequest
from app.services.layout_reference import (
    LayoutReferenceError,
    create_layout_reference,
    get_layout_reference_preview_asset,
)

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
    except LayoutReferenceError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("解析排版参考失败", exc_info=exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="参考页面解析失败，请稍后重试或更换公开文章链接") from exc


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
