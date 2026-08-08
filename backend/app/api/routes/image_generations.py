"""Document-scoped image generation and controlled asset application."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.ai_image_model import AIImageModel
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_version import DocumentVersionSource
from app.models.image_generation import (
    GeneratedImageAsset,
    ImageGeneration,
    ImageGenerationPurpose,
    ImageGenerationSource,
    ImageGenerationStatus,
)
from app.models.user import User
from app.schemas.image_generation import ImageGenerationApply, ImageGenerationCreate, ImageGenerationRead
from app.services.document_access import can_access_document
from app.services.document_activity import touch_document
from app.services.document_images import StoredDocumentImage, delete_tracked_document_image
from app.services.document_versions import create_document_version
from app.services.html_workspace import HtmlWorkspace, WorkspaceError
from app.services.image_generation import create_generation, generation_payload, start_generation
from app.services.model_access import can_access_image_model


router = APIRouter(prefix="/api/documents", tags=["image-generations"])
ACTIVE_AGENT_STATUSES = {
    AgentRunStatus.PENDING,
    AgentRunStatus.RUNNING,
    AgentRunStatus.WAITING_FOR_INPUT,
    AgentRunStatus.CANCELLING,
}


def _document_or_404(db: Session, document_id: int, user: User, *, lock: bool = False) -> Document:
    query = db.query(Document).filter(Document.id == document_id)
    if lock:
        query = query.with_for_update()
    document = query.first()
    if not document or not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return document


def _generation_or_404(db: Session, document_id: int, generation_id: str, user: User) -> ImageGeneration:
    generation = (
        db.query(ImageGeneration)
        .options(joinedload(ImageGeneration.assets))
        .filter(ImageGeneration.id == generation_id, ImageGeneration.document_id == document_id)
        .first()
    )
    _document_or_404(db, document_id, user)
    if generation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片生成任务不存在")
    return generation


def _require_idle_document(db: Session, document_id: int) -> None:
    if db.query(AgentRun.id).filter(AgentRun.document_id == document_id, AgentRun.status.in_(ACTIVE_AGENT_STATUSES)).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前推文正在由 AI 编辑，请完成或停止后再应用图片")


@router.get("/{document_id}/image-generations", response_model=list[ImageGenerationRead])
def list_image_generations(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    _document_or_404(db, document_id, current_user)
    rows = (
        db.query(ImageGeneration)
        .options(joinedload(ImageGeneration.assets))
        .filter(ImageGeneration.document_id == document_id)
        .order_by(ImageGeneration.created_at.desc())
        .limit(40)
        .all()
    )
    return [generation_payload(row) for row in rows]


@router.get("/{document_id}/image-generations/workspace")
def get_image_generation_workspace(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _document_or_404(db, document_id, current_user)
    return HtmlWorkspace(document.current_html).map_payload(limit=72)


@router.post("/{document_id}/image-generations", response_model=ImageGenerationRead, status_code=status.HTTP_202_ACCEPTED)
async def create_document_image_generation(
    document_id: int,
    payload: ImageGenerationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _document_or_404(db, document_id, current_user)
    if payload.session_id is not None:
        session = db.get(ChatSession, payload.session_id)
        if session is None or session.document_id != document_id or session.is_archived:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对话不存在")
    model = db.get(AIImageModel, payload.model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片模型不存在")
    if not can_access_image_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该图片模型的权限")
    if not model.provider.image_protocol or not model.provider.image_base_url:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该 Provider 尚未配置图片生成端点")
    existing = (
        db.query(ImageGeneration)
        .filter(
            ImageGeneration.document_id == document_id,
            ImageGeneration.user_id == current_user.id,
            ImageGeneration.model_id == model.id,
            ImageGeneration.purpose == ImageGenerationPurpose(payload.purpose),
            ImageGeneration.prompt == payload.prompt,
            ImageGeneration.status.in_([ImageGenerationStatus.PENDING, ImageGenerationStatus.RUNNING]),
        )
        .order_by(ImageGeneration.created_at.desc())
        .first()
    )
    if existing is not None:
        return generation_payload(existing)
    generation = create_generation(
        db,
        document_id=document_id,
        session_id=payload.session_id,
        model_id=model.id,
        user_id=current_user.id,
        source=ImageGenerationSource.EDITOR,
        purpose=ImageGenerationPurpose(payload.purpose),
        prompt=payload.prompt,
        quantity=payload.quantity,
        aspect_ratio=payload.aspect_ratio,
        quality=payload.quality,
        anchor_block_id=payload.anchor_block_id,
        direct_insert=payload.direct_insert,
    )
    db.commit()
    db.refresh(generation)
    start_generation(generation.id)
    return generation_payload(generation)


@router.get("/{document_id}/image-generations/{generation_id}", response_model=ImageGenerationRead)
def get_document_image_generation(
    document_id: int,
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return generation_payload(_generation_or_404(db, document_id, generation_id, current_user))


@router.post("/{document_id}/image-generations/{generation_id}/cancel", response_model=ImageGenerationRead)
def cancel_document_image_generation(
    document_id: int,
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    generation = _generation_or_404(db, document_id, generation_id, current_user)
    if generation.status in {ImageGenerationStatus.PENDING, ImageGenerationStatus.RUNNING}:
        generation.cancel_requested = True
        if generation.status == ImageGenerationStatus.PENDING:
            generation.status = ImageGenerationStatus.CANCELLED
            generation.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(generation)
    return generation_payload(generation)


@router.delete(
    "/{document_id}/image-generations/{generation_id}/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_document_generated_image(
    document_id: int,
    generation_id: str,
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    generation = _generation_or_404(db, document_id, generation_id, current_user)
    asset = next((item for item in generation.assets if item.id == asset_id), None)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成图片不存在")
    if asset.is_applied:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已应用到文章的图片不能删除")
    delete_tracked_document_image(
        db, StoredDocumentImage(url=asset.url, object_key=asset.object_key, storage_mode=asset.storage_mode)
    )
    db.delete(asset)
    db.commit()


@router.post("/{document_id}/image-generations/{generation_id}/assets/{asset_id}/apply", response_model=ImageGenerationRead)
def apply_document_generated_image(
    document_id: int,
    generation_id: str,
    asset_id: str,
    payload: ImageGenerationApply,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    generation = _generation_or_404(db, document_id, generation_id, current_user)
    asset = next((item for item in generation.assets if item.id == asset_id), None)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成图片不存在")
    if generation.status != ImageGenerationStatus.SUCCEEDED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="图片生成尚未完成或结果不可用")
    # A generation's purpose is a composition hint rather than a restriction
    # on where its saved candidate can be used.  This permits a wide cover to
    # be reused as an inline banner when the user chooses it.
    document = _document_or_404(db, document_id, current_user, lock=True)
    _require_idle_document(db, document_id)
    if payload.target == "cover":
        document.wechat_cover_url = asset.url
        document.wechat_pic_crop_235_1 = ""
        document.wechat_pic_crop_1_1 = ""
        label = "AI 生成封面"
    else:
        if not payload.revision or not payload.anchor_block_id or not payload.expected_hash:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="正文插图需要文档版本和目标段落")
        workspace = HtmlWorkspace(document.current_html)
        alt = html.escape(payload.alt.strip() or generation.prompt[:120], quote=True)
        image_html = (
            f'<p><img src="{html.escape(asset.url, quote=True)}" alt="{alt}" '
            'style="display:block;width:100%;height:auto;max-width:100%;" /></p>'
        )
        try:
            next_html, _ = workspace.apply_patch(
                payload.revision,
                [{
                    "block_id": payload.anchor_block_id,
                    "expected_hash": payload.expected_hash,
                    "mode": "insert_after",
                    "html": image_html,
                }],
                lambda value: value,
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        document.current_html = next_html
        label = "AI 生成正文配图"
    asset.is_applied = True
    asset.applied_at = datetime.now(timezone.utc)
    touch_document(document, current_user.id)
    create_document_version(db, document, current_user.id, DocumentVersionSource.AI, label)
    db.commit()
    db.refresh(generation)
    return generation_payload(generation)
