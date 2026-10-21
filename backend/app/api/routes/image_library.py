from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.api.routes.image_generations import _document_or_404, _require_idle_document
from app.db.session import get_db
from app.models.image_generation import ImageLibraryAsset, ImageLibraryMode, ImageLibrarySource
from app.models.user import User
from app.schemas.image_library import (
    ImageLibraryAssetRead,
    ImageLibraryAssetUpdate,
    ImageLibraryBulkDelete,
    ImageLibraryCoverApply,
    ImageLibraryListRead,
    ImageLibrarySearchImport,
    ImageLibrarySettingsRead,
    ImageLibrarySettingsUpdate,
)
from app.schemas.chat_images import ChatImageAttachmentRead, ChatImageLibraryReference, ChatImageLibraryBatchReference
from app.services.chat_images import MAX_CHAT_IMAGES_PER_MESSAGE, ChatImageError, create_library_attachment
from app.services import local_uploads
from app.services.document_activity import touch_document
from app.services.document_images import (
    MAX_DOCUMENT_IMAGE_BYTES,
    DocumentImageStorageError,
    StoredDocumentImage,
    delete_tracked_document_image,
    store_tracked_document_image,
)
from app.services.document_versions import create_document_version
from app.models.document_version import DocumentVersionSource
from app.services.image_library import (
    asset_payload,
    create_library_asset,
    get_or_create_settings,
    library_mode,
    refreshed_asset_url,
    soft_delete,
)
from app.services.image_search import (
    ImageSearchError,
    ImageSearchTokenError,
    decode_candidate_token,
    fetch_candidate_image,
)


router = APIRouter(prefix="/api/image-library", tags=["image-library"])
logger = logging.getLogger(__name__)


def _visible_query(db: Session, user: User):
    query = db.query(ImageLibraryAsset).filter(ImageLibraryAsset.deleted_at.is_(None))
    mode = library_mode(db)
    if mode == ImageLibraryMode.SHARED:
        query = query.filter(ImageLibraryAsset.is_shared.is_(True))
    else:
        query = query.filter(ImageLibraryAsset.owner_id == user.id)
    return query, mode


def _asset_or_404(db: Session, asset_id: str, user: User) -> tuple[ImageLibraryAsset, ImageLibraryMode]:
    query, mode = _visible_query(db, user)
    asset = query.filter(ImageLibraryAsset.id == asset_id).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在或不可用")
    return asset, mode


@router.get("/settings", response_model=ImageLibrarySettingsRead)
def get_image_library_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    del current_user
    settings = get_or_create_settings(db)
    db.commit()
    db.refresh(settings)
    return {"mode": settings.mode.value, "updated_at": settings.updated_at}


@router.get("/settings/assets", response_model=list[ImageLibraryAssetRead])
def list_settings_assets(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = (
        db.query(ImageLibraryAsset)
        .filter(ImageLibraryAsset.deleted_at.is_(None))
        .order_by(ImageLibraryAsset.created_at.desc())
        .all()
    )
    return [asset_payload(db, row, current_user, ImageLibraryMode.SHARED) for row in rows]


@router.put("/settings", response_model=ImageLibrarySettingsRead)
def update_image_library_settings(
    payload: ImageLibrarySettingsUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_or_create_settings(db)
    selected = set(payload.shared_asset_ids)
    if payload.mode == "shared":
        existing = {
            row[0]
            for row in db.query(ImageLibraryAsset.id)
            .filter(ImageLibraryAsset.deleted_at.is_(None), ImageLibraryAsset.id.in_(selected))
            .all()
        } if selected else set()
        if existing != selected:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="共享图片选择中包含不存在的素材")
        db.query(ImageLibraryAsset).filter(ImageLibraryAsset.deleted_at.is_(None)).update(
            {ImageLibraryAsset.is_shared: False}, synchronize_session=False
        )
        if selected:
            db.query(ImageLibraryAsset).filter(ImageLibraryAsset.id.in_(selected)).update(
                {ImageLibraryAsset.is_shared: True}, synchronize_session=False
            )
    settings.mode = ImageLibraryMode(payload.mode)
    settings.updated_by_id = current_user.id
    db.commit()
    db.refresh(settings)
    return {"mode": settings.mode.value, "updated_at": settings.updated_at}


@router.get("/assets", response_model=ImageLibraryListRead)
def list_image_library_assets(
    q: str = Query(default="", max_length=256),
    source: Literal["all", "upload", "ai", "search"] = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query, mode = _visible_query(db, current_user)
    if q.strip():
        query = query.filter(ImageLibraryAsset.name.ilike(f"%{q.strip()}%"))
    if source != "all":
        query = query.filter(ImageLibraryAsset.source == ImageLibrarySource(source))
    total = query.with_entities(func.count(ImageLibraryAsset.id)).scalar() or 0
    rows = (
        query.order_by(ImageLibraryAsset.created_at.desc(), ImageLibraryAsset.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [asset_payload(db, row, current_user, mode) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "mode": mode.value,
    }


@router.post("/assets/upload", response_model=list[ImageLibraryAssetRead], status_code=status.HTTP_201_CREATED)
async def upload_image_library_assets(
    files: list[UploadFile] = File(...),
    document_id: int | None = Query(default=None, gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    if not files or len(files) > MAX_CHAT_IMAGES_PER_MESSAGE:
        for file in files:
            await file.close()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"每次可上传 1 到 {MAX_CHAT_IMAGES_PER_MESSAGE} 张图片")
    if document_id is not None:
        _document_or_404(db, document_id, current_user)
    stored_rows: list[StoredDocumentImage] = []
    assets: list[ImageLibraryAsset] = []
    try:
        for file in files:
            data = await file.read(MAX_DOCUMENT_IMAGE_BYTES + 1)
            if len(data) > MAX_DOCUMENT_IMAGE_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="单张图片不能超过 10MB")
            image = local_uploads.inspect_image(data)
            stored = store_tracked_document_image(db, data, file.filename or "image")
            stored_rows.append(stored)
            assets.append(create_library_asset(
                db,
                owner_id=current_user.id,
                document_id=document_id,
                name=file.filename or "图片",
                source=ImageLibrarySource.UPLOAD,
                stored=stored,
                content_type=image.content_type,
                size=len(data),
                width=image.width,
                height=image.height,
            ))
        db.commit()
        for asset in assets:
            db.refresh(asset)
        mode = library_mode(db)
        return [asset_payload(db, asset, current_user, mode) for asset in assets]
    except HTTPException:
        db.rollback()
        for stored in stored_rows:
            delete_tracked_document_image(db, stored)
        raise
    except (local_uploads.LocalUploadError, DocumentImageStorageError) as exc:
        db.rollback()
        for stored in stored_rows:
            delete_tracked_document_image(db, stored)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        for file in files:
            await file.close()


@router.post("/assets/import-search", response_model=ImageLibraryAssetRead, status_code=status.HTTP_201_CREATED)
async def import_searched_image(
    payload: ImageLibrarySearchImport,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _document_or_404(db, payload.document_id, current_user)
    try:
        candidate = decode_candidate_token(
            payload.candidate_token, user_id=current_user.id, document_id=payload.document_id
        )
        data, image = await fetch_candidate_image(candidate)
        stored = store_tracked_document_image(db, data, f"image-search-{candidate.id}")
    except ImageSearchTokenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (ImageSearchError, ValueError, DocumentImageStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    try:
        asset = create_library_asset(
            db,
            owner_id=current_user.id,
            document_id=payload.document_id,
            name=candidate.title or "搜索图片",
            source=ImageLibrarySource.SEARCH,
            stored=stored,
            content_type=image.content_type,
            size=len(data),
            width=image.width,
            height=image.height,
        )
        db.commit()
        db.refresh(asset)
        return asset_payload(db, asset, current_user)
    except Exception:
        db.rollback()
        delete_tracked_document_image(db, stored)
        raise


@router.patch("/assets/{asset_id}", response_model=ImageLibraryAssetRead)
def update_image_library_asset(
    asset_id: str,
    payload: ImageLibraryAssetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    asset, mode = _asset_or_404(db, asset_id, current_user)
    asset.name = payload.name.strip()
    db.commit()
    db.refresh(asset)
    return asset_payload(db, asset, current_user, mode)


@router.post("/assets/{asset_id}/chat-reference", response_model=ChatImageAttachmentRead, status_code=status.HTTP_201_CREATED)
def reference_image_library_asset(
    asset_id: str,
    payload: ChatImageLibraryReference,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.api.routes.chat import _attachment_read

    asset, _ = _asset_or_404(db, asset_id, current_user)
    _document_or_404(db, payload.document_id, current_user)
    try:
        attachment = create_library_attachment(
            db, asset=asset, document_id=payload.document_id, uploader_id=current_user.id
        )
        db.commit()
        db.refresh(attachment)
        return _attachment_read(attachment, current_user)
    except Exception as exc:
        db.rollback()
        code = status.HTTP_400_BAD_REQUEST if isinstance(exc, ChatImageError) else status.HTTP_503_SERVICE_UNAVAILABLE
        detail = str(exc) if isinstance(exc, ChatImageError) else "图库图片引用失败，请稍后重试"
        raise HTTPException(status_code=code, detail=detail) from exc


@router.post("/assets/chat-references", response_model=list[ChatImageAttachmentRead], status_code=status.HTTP_201_CREATED)
def reference_image_library_assets(
    payload: ChatImageLibraryBatchReference,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    from app.api.routes.chat import _attachment_read

    _document_or_404(db, payload.document_id, current_user)
    if len(set(payload.asset_ids)) != len(payload.asset_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="不能重复选择同一张图片")
    assets = [_asset_or_404(db, asset_id, current_user)[0] for asset_id in payload.asset_ids]
    try:
        attachments = [create_library_attachment(
            db, asset=asset, document_id=payload.document_id, uploader_id=current_user.id
        ) for asset in assets]
        db.commit()
        return [_attachment_read(attachment, current_user) for attachment in attachments]
    except Exception as exc:
        db.rollback()
        code = status.HTTP_400_BAD_REQUEST if isinstance(exc, ChatImageError) else status.HTTP_503_SERVICE_UNAVAILABLE
        detail = str(exc) if isinstance(exc, ChatImageError) else "图库图片引用失败，请稍后重试"
        raise HTTPException(status_code=code, detail=detail) from exc


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_image_library_asset(
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    asset, _ = _asset_or_404(db, asset_id, current_user)
    soft_delete(asset)
    db.commit()


@router.post("/assets/bulk-delete", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def bulk_delete_image_library_assets(
    payload: ImageLibraryBulkDelete,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    query, _ = _visible_query(db, current_user)
    rows = query.filter(ImageLibraryAsset.id.in_(set(payload.asset_ids))).all()
    if len(rows) != len(set(payload.asset_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部分图片不存在或不可管理")
    for row in rows:
        soft_delete(row)
    db.commit()


@router.post("/assets/{asset_id}/cover", response_model=ImageLibraryAssetRead)
def set_image_library_asset_as_cover(
    asset_id: str,
    payload: ImageLibraryCoverApply,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    asset, mode = _asset_or_404(db, asset_id, current_user)
    document = _document_or_404(db, payload.document_id, current_user, lock=True)
    _require_idle_document(db, payload.document_id)
    document.wechat_cover_url = refreshed_asset_url(db, asset)
    document.wechat_pic_crop_235_1 = ""
    document.wechat_pic_crop_1_1 = ""
    touch_document(document, current_user.id)
    create_document_version(db, document, current_user.id, DocumentVersionSource.MANUAL, "图片库设置封面")
    db.commit()
    db.refresh(asset)
    return asset_payload(db, asset, current_user, mode)
