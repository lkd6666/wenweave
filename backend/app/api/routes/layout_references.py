import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.layout_reference import LayoutReferencePreview, LayoutReferencePreviewRequest
from app.services.layout_reference import LayoutReferenceError, create_layout_reference

router = APIRouter(prefix="/api/layout-references", tags=["layout-references"])
logger = logging.getLogger(__name__)


@router.post("/preview", response_model=LayoutReferencePreview)
async def preview_layout_reference(
    payload: LayoutReferencePreviewRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return (await create_layout_reference(payload.url, current_user.id)).preview_payload()
    except LayoutReferenceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("解析排版参考失败", exc_info=exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="参考页面解析失败，请稍后重试或更换公开文章链接") from exc
