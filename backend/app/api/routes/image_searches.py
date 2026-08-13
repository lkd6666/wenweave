from __future__ import annotations

import html

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.image_generations import _document_or_404, _require_idle_document
from app.db.session import get_db
from app.models.document_version import DocumentVersionSource
from app.models.user import User
from app.schemas.image_search import ImageSearchApply, ImageSearchApplyResult, ImageSearchRequest, ImageSearchResponse
from app.services.document_activity import touch_document
from app.services.document_images import StoredDocumentImage, delete_tracked_document_image, store_tracked_document_image
from app.services.document_versions import create_document_version
from app.services.html_workspace import HtmlWorkspace, WorkspaceError
from app.services.image_generation import image_target_fingerprint, replace_image_source
from app.services.image_search import (
    IMAGE_SEARCH_NOTICE,
    ImageSearchError,
    ImageSearchTokenError,
    candidate_payload,
    decode_candidate_token,
    fetch_candidate_image,
    fetch_candidate_preview,
    issue_candidate_token,
    search_image_page,
)


router = APIRouter(tags=["image-searches"])


@router.post("/api/documents/{document_id}/image-searches", response_model=ImageSearchResponse)
async def search_document_images(
    document_id: int,
    payload: ImageSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _document_or_404(db, document_id, current_user)
    try:
        candidates, has_more = await search_image_page(payload.query, payload.page, payload.orientation)
    except ImageSearchError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    items = [
        candidate_payload(candidate, issue_candidate_token(candidate, user_id=current_user.id, document_id=document_id))
        for candidate in candidates
    ]
    return {
        "query": payload.query,
        "page": payload.page,
        "next_page": payload.page + 1 if has_more and payload.page < 5 else None,
        "notice": IMAGE_SEARCH_NOTICE,
        "items": items,
    }


@router.get("/api/image-search/preview")
async def preview_searched_image(token: str) -> Response:
    try:
        candidate = decode_candidate_token(token)
        data, image = await fetch_candidate_preview(candidate)
    except (ImageSearchError, ImageSearchTokenError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=image.content_type,
        headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/api/documents/{document_id}/image-searches/apply", response_model=ImageSearchApplyResult)
async def apply_searched_image(
    document_id: int,
    payload: ImageSearchApply,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _document_or_404(db, document_id, current_user)
    try:
        candidate = decode_candidate_token(payload.candidate_token, user_id=current_user.id, document_id=document_id)
        data, image = await fetch_candidate_image(candidate)
    except ImageSearchTokenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (ImageSearchError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stored: StoredDocumentImage | None = None
    try:
        document = _document_or_404(db, document_id, current_user, lock=True)
        _require_idle_document(db, document_id)
        if payload.target == "cover":
            label = "搜图设置封面"
            next_target = "cover"
        elif payload.target_image_index >= 0:
            if not payload.revision or not payload.source_image_url:
                raise HTTPException(status_code=422, detail="替换图片需要文档版本和目标图片")
            workspace = HtmlWorkspace(document.current_html)
            if workspace.revision != payload.revision:
                raise HTTPException(status_code=409, detail="文档已发生变化，请刷新后重新选择图片")
            current_hash = image_target_fingerprint(document.current_html, payload.target_image_index, payload.source_image_url)
            if not current_hash or (payload.source_image_hash and current_hash != payload.source_image_hash):
                raise HTTPException(status_code=409, detail="目标图片已发生变化，请重新选择")
            label = "搜图替换图片"
            next_target = "replace"
        else:
            if not payload.revision or not payload.anchor_block_id or not payload.expected_hash:
                raise HTTPException(status_code=422, detail="正文插图需要文档版本和目标段落")
            workspace = HtmlWorkspace(document.current_html)
            if workspace.revision != payload.revision:
                raise HTTPException(status_code=409, detail="文档已发生变化，请刷新后重新选择图片")
            label = "搜图添加正文配图"
            next_target = "body"

        stored = store_tracked_document_image(db, data, f"image-search-{candidate.id}")
        from app.services.image_library import create_library_asset
        from app.models.image_generation import ImageLibrarySource

        create_library_asset(
            db,
            owner_id=current_user.id,
            document_id=document_id,
            name=candidate.title or "搜索图片",
            source=ImageLibrarySource.SEARCH,
            stored=stored,
            content_type=image.content_type,
            size=len(data),
            width=image.width,
            height=image.height,
        )
        if payload.target == "cover":
            document.wechat_cover_url = stored.url
            document.wechat_pic_crop_235_1 = ""
            document.wechat_pic_crop_1_1 = ""
        elif payload.target_image_index >= 0:
            document.current_html = replace_image_source(
                document.current_html,
                payload.target_image_index,
                payload.source_image_url,
                stored.url,
            )
        else:
            image_html = (
                f'<p><img src="{html.escape(stored.url, quote=True)}" '
                f'alt="{html.escape(payload.alt.strip() or candidate.title, quote=True)}" '
                'style="display:block;width:100%;height:auto;max-width:100%;" /></p>'
            )
            document.current_html, _ = workspace.apply_patch(
                payload.revision,
                [{
                    "block_id": payload.anchor_block_id,
                    "expected_hash": payload.expected_hash,
                    "mode": "insert_after",
                    "html": image_html,
                }],
                lambda value: value,
            )
        touch_document(document, current_user.id)
        create_document_version(db, document, current_user.id, DocumentVersionSource.MANUAL, label)
        db.commit()
        return {
            "ok": True,
            "target": next_target,
            "url": stored.url,
            "revision": HtmlWorkspace(document.current_html).revision if next_target != "cover" else "",
        }
    except HTTPException:
        db.rollback()
        if stored is not None:
            delete_tracked_document_image(db, stored)
        raise
    except (WorkspaceError, ValueError) as exc:
        db.rollback()
        if stored is not None:
            delete_tracked_document_image(db, stored)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        if stored is not None:
            delete_tracked_document_image(db, stored)
        raise
