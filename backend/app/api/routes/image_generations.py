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
    ImageGenerationOperation,
    ImageGenerationPurpose,
    ImageGenerationSource,
    ImageGenerationStatus,
    ImageLibraryAsset,
)
from app.models.storage_config import StorageConfig
from app.models.user import User
from app.schemas.image_generation import (
    ImageGenerationApply,
    ImageGenerationCreate,
    ImageGenerationRead,
    ImageGenerationWorkspaceResolve,
)
from app.services.document_access import can_access_document
from app.services.document_activity import touch_document
from app.services.document_images import StoredDocumentImage, delete_tracked_document_image, store_tracked_document_image
from app.services.document_versions import create_document_version
from app.services.html_workspace import HtmlWorkspace, WorkspaceError
from app.services.image_generation import (
    create_generation,
    generation_payload,
    image_target_fingerprint,
    materialize_source_image,
    replace_image_source,
    start_generation,
)
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


def _generation_payload(generation: ImageGeneration, document: Document) -> dict:
    return generation_payload(
        generation,
        current_html=getattr(document, "current_html", ""),
        cover_url=getattr(document, "wechat_cover_url", ""),
    )


@router.get("/{document_id}/image-generations", response_model=list[ImageGenerationRead])
def list_image_generations(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    document = _document_or_404(db, document_id, current_user)
    rows = (
        db.query(ImageGeneration)
        .options(joinedload(ImageGeneration.assets))
        .filter(ImageGeneration.document_id == document_id)
        .order_by(ImageGeneration.created_at.desc())
        .limit(40)
        .all()
    )
    return [_generation_payload(row, document) for row in rows]


@router.get("/{document_id}/image-generations/workspace")
def get_image_generation_workspace(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _document_or_404(db, document_id, current_user)
    return HtmlWorkspace(document.current_html).map_payload(limit=72)


@router.post("/{document_id}/image-generations/workspace/resolve")
def resolve_image_generation_workspace_selection(
    document_id: int,
    payload: ImageGenerationWorkspaceResolve,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve a preview click to its current, server-validated insertion block."""
    document = _document_or_404(db, document_id, current_user)
    workspace = HtmlWorkspace(document.current_html)
    resolution = workspace.resolve_selection(
        payload.selector,
        payload.tag_name,
        payload.text,
        payload.html,
        payload.locator,
    )
    if resolution.block is None:
        detail = resolution.reason or "无法确认图片插入位置，请重新选择正文段落"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return {
        "revision": workspace.revision,
        "status": resolution.status,
        "reason": resolution.reason,
        "block": resolution.block.map_item(),
    }


@router.post("/{document_id}/image-generations", response_model=ImageGenerationRead, status_code=status.HTTP_202_ACCEPTED)
async def create_document_image_generation(
    document_id: int,
    payload: ImageGenerationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _document_or_404(db, document_id, current_user)
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
    if payload.operation not in model.operations:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该图片模型不支持 AI 图片编辑")
    if payload.operation == "edit" and (not payload.source_image_url or payload.target_image_index < 0):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="AI 图片编辑需要当前文章图片")
    source_hash = ""
    if payload.target_image_index >= 0:
        source_hash = image_target_fingerprint(
            document.current_html,
            payload.target_image_index,
            payload.source_image_url,
        )
        if not source_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="目标图片已发生变化，请重新选择")
    existing = (
        db.query(ImageGeneration)
        .filter(
            ImageGeneration.document_id == document_id,
            ImageGeneration.user_id == current_user.id,
            ImageGeneration.model_id == model.id,
            ImageGeneration.purpose == ImageGenerationPurpose(payload.purpose),
            ImageGeneration.operation == ImageGenerationOperation(payload.operation),
            ImageGeneration.prompt == payload.prompt,
            ImageGeneration.timeout_seconds == payload.timeout_seconds,
            ImageGeneration.source_image_url == payload.source_image_url,
            ImageGeneration.target_image_index == payload.target_image_index,
            ImageGeneration.status.in_([ImageGenerationStatus.PENDING, ImageGenerationStatus.RUNNING]),
        )
        .order_by(ImageGeneration.created_at.desc())
        .first()
    )
    if existing is not None:
        return _generation_payload(existing, document)
    source_data: bytes | None = None
    if payload.operation == "edit":
        try:
            source_data, _ = await materialize_source_image(
                payload.source_image_url,
                storage=db.query(StorageConfig).first(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
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
        timeout_seconds=payload.timeout_seconds,
        anchor_block_id=payload.anchor_block_id,
        direct_insert=payload.direct_insert,
        operation=ImageGenerationOperation(payload.operation),
        source_image_url=payload.source_image_url,
        source_image_hash=source_hash,
        target_image_index=payload.target_image_index,
    )
    stored_source: StoredDocumentImage | None = None
    try:
        if source_data is not None:
            stored_source = store_tracked_document_image(db, source_data, f"ai-edit-source-{generation.id}.png")
            generation.source_asset_url = stored_source.url
            generation.source_object_key = stored_source.object_key
            generation.source_storage_mode = stored_source.storage_mode
        db.commit()
    except ValueError as exc:
        db.rollback()
        if stored_source is not None:
            delete_tracked_document_image(db, stored_source)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.refresh(generation)
    start_generation(generation.id)
    return _generation_payload(generation, document)


@router.get("/{document_id}/image-generations/{generation_id}", response_model=ImageGenerationRead)
def get_document_image_generation(
    document_id: int,
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    generation = _generation_or_404(db, document_id, generation_id, current_user)
    document = _document_or_404(db, document_id, current_user)
    return _generation_payload(generation, document)


@router.post("/{document_id}/image-generations/{generation_id}/cancel", response_model=ImageGenerationRead)
def cancel_document_image_generation(
    document_id: int,
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    generation = _generation_or_404(db, document_id, generation_id, current_user)
    document = _document_or_404(db, document_id, current_user)
    if generation.status in {ImageGenerationStatus.PENDING, ImageGenerationStatus.RUNNING}:
        generation.cancel_requested = True
        if generation.status == ImageGenerationStatus.PENDING:
            generation.status = ImageGenerationStatus.CANCELLED
            generation.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(generation)
    return _generation_payload(generation, document)


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
    library_asset = (
        db.query(ImageLibraryAsset)
        .filter(
            ImageLibraryAsset.generated_asset_id == asset.id,
            ImageLibraryAsset.deleted_at.is_(None),
        )
        .first()
    )
    if library_asset is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="图片已保存到图片库，请在图库中移出")
    if asset.is_applied:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已应用到文章的图片不能删除")
    from app.models.chat_image_attachment import ChatImageAttachment
    if db.query(ChatImageAttachment.id).filter(
        ChatImageAttachment.storage_mode == asset.storage_mode,
        ChatImageAttachment.object_key == asset.object_key,
    ).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="图片已被对话引用，不能删除")
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
    elif getattr(generation, "target_image_index", -1) >= 0 or payload.target_image_index >= 0:
        generation_target_index = getattr(generation, "target_image_index", -1)
        target_index = generation_target_index if generation_target_index >= 0 else payload.target_image_index
        if not payload.revision or payload.target_image_index != target_index:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="替换图片需要文档版本和目标图片")
        workspace = HtmlWorkspace(document.current_html)
        if workspace.map_payload(limit=1).get("revision") != payload.revision:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="文档已发生变化，请刷新后重新选择图片")
        generation_source_url = getattr(generation, "source_image_url", "")
        generation_source_hash = getattr(generation, "source_image_hash", "")
        source_url = payload.source_image_url or generation_source_url
        source_hash = payload.source_image_hash or generation_source_hash
        # A candidate created by the regular AI 配图 flow has no generation
        # target. In the AI 换图 modal the editor supplies the current image as
        # an explicit replacement target, so validate that target instead of
        # requiring it to match the candidate's original metadata.
        if generation_target_index >= 0 and (
            source_url != generation_source_url or (source_hash and source_hash != generation_source_hash)
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="目标图片校验失败，请重新选择")
        current_hash = image_target_fingerprint(document.current_html, target_index, source_url)
        if not current_hash or (generation_target_index >= 0 and current_hash != generation_source_hash) or (
            generation_target_index < 0 and source_hash and current_hash != source_hash
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="目标图片已发生变化，请重新选择")
        try:
            document.current_html = replace_image_source(
                document.current_html,
                target_index,
                source_url,
                asset.url,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        label = "AI 编辑图片" if getattr(generation, "operation", ImageGenerationOperation.GENERATE) == ImageGenerationOperation.EDIT else "AI 换图"
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
    return _generation_payload(generation, document)
