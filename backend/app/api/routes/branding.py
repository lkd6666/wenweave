from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import get_settings
from app.db.session import get_db
from app.models.app_branding import AppBranding
from app.schemas.branding import AppBrandingRead, AppBrandingUpdate
from app.services.local_uploads import LocalUploadError, inspect_image


router = APIRouter(prefix="/api/branding", tags=["branding"])

MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_FAVICON_BYTES = 512 * 1024
BRANDING_ID = 1


def _branding_payload(branding: AppBranding | None) -> dict:
    if branding is None:
        return {
            "system_name": get_settings().APP_NAME,
            "logo_url": None,
            "logo_content_type": "",
            "favicon_url": None,
            "favicon_content_type": "",
            "updated_at": None,
        }
    return {
        "system_name": branding.system_name,
        "logo_url": "/api/branding/assets/logo" if branding.logo_data else None,
        "logo_content_type": branding.logo_content_type if branding.logo_data else "",
        "favicon_url": "/api/branding/assets/favicon" if branding.favicon_data else None,
        "favicon_content_type": branding.favicon_content_type if branding.favicon_data else "",
        "updated_at": branding.updated_at,
    }


def _get_or_create_branding(db: Session) -> AppBranding:
    branding = db.get(AppBranding, BRANDING_ID)
    if branding is None:
        branding = AppBranding(id=BRANDING_ID, system_name=get_settings().APP_NAME)
        db.add(branding)
        db.flush()
    return branding


def _asset_or_404(db: Session, kind: str) -> tuple[bytes, str]:
    branding = db.get(AppBranding, BRANDING_ID)
    if branding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="品牌素材不存在")
    if kind == "logo":
        data, content_type = branding.logo_data, branding.logo_content_type
    elif kind == "favicon":
        data, content_type = branding.favicon_data, branding.favicon_content_type
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="品牌素材不存在")
    if not data or not content_type:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="品牌素材不存在")
    return data, content_type


async def _read_image(file: UploadFile, maximum_size: int) -> tuple[bytes, str]:
    try:
        data = await file.read(maximum_size + 1)
        if len(data) > maximum_size:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="图片文件过大")
        image = inspect_image(data)
        return data, image.content_type
    except LocalUploadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        await file.close()


@router.get("", response_model=AppBrandingRead)
def get_branding(db: Session = Depends(get_db)) -> dict:
    return _branding_payload(db.get(AppBranding, BRANDING_ID))


@router.get("/assets/{kind}")
def get_branding_asset(kind: str, db: Session = Depends(get_db)) -> Response:
    data, content_type = _asset_or_404(db, kind)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.put("", response_model=AppBrandingRead)
def update_branding(
    payload: AppBrandingUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    system_name = payload.system_name.strip()
    if not system_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="系统名称不能为空")
    branding = _get_or_create_branding(db)
    branding.system_name = system_name
    branding.updated_by_id = current_user.id
    db.commit()
    db.refresh(branding)
    return _branding_payload(branding)


@router.post("/logo", response_model=AppBrandingRead)
async def upload_logo(
    file: UploadFile = File(...),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    data, content_type = await _read_image(file, MAX_LOGO_BYTES)
    branding = _get_or_create_branding(db)
    branding.logo_data = data
    branding.logo_content_type = content_type
    branding.updated_by_id = current_user.id
    db.commit()
    db.refresh(branding)
    return _branding_payload(branding)


@router.post("/favicon", response_model=AppBrandingRead)
async def upload_favicon(
    file: UploadFile = File(...),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    data, content_type = await _read_image(file, MAX_FAVICON_BYTES)
    branding = _get_or_create_branding(db)
    branding.favicon_data = data
    branding.favicon_content_type = content_type
    branding.updated_by_id = current_user.id
    db.commit()
    db.refresh(branding)
    return _branding_payload(branding)


@router.delete("/assets/{kind}", response_model=AppBrandingRead)
def delete_branding_asset(
    kind: str,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    branding = _get_or_create_branding(db)
    if kind == "logo":
        branding.logo_data = None
        branding.logo_content_type = ""
    elif kind == "favicon":
        branding.favicon_data = None
        branding.favicon_content_type = ""
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="品牌素材不存在")
    branding.updated_by_id = current_user.id
    db.commit()
    db.refresh(branding)
    return _branding_payload(branding)
