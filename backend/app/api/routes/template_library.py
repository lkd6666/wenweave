from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.ai_model import AIModel
from app.models.template_library import (
    TemplateCategory,
    TemplateGeneration,
    TemplateGenerationStatus,
    TemplateImageAsset,
    TemplateLibraryItem,
    TemplateSourceType,
)
from app.models.user import User
from app.schemas.template_library import (
    TemplateCategoryCreate,
    TemplateCategoryRead,
    TemplateCategoryUpdate,
    TemplateGenerationCreate,
    TemplateGenerationRead,
    TemplateGenerationSave,
    TemplateItemCreate,
    TemplateItemRead,
    TemplateItemUpdate,
)
from app.services.model_access import can_access_model
from app.services.template_library import (
    TemplateLibraryError,
    category_or_error,
    delete_asset_object,
    generation_payload,
    localize_template_html,
    read_asset_bytes,
    remove_unreferenced_assets,
    start_generation,
    template_payload,
)


router = APIRouter(prefix="/api/template-library", tags=["template-library"])


def _category_read(category: TemplateCategory) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "sort_order": category.sort_order,
        "created_at": category.created_at,
        "updated_at": category.updated_at,
    }


def _template_or_404(db: Session, template_id: int) -> TemplateLibraryItem:
    template = db.get(TemplateLibraryItem, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    return template


def _category_or_404(db: Session, category_id: int) -> TemplateCategory:
    category = db.get(TemplateCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板分类不存在")
    return category


@router.get("/categories", response_model=list[TemplateCategoryRead])
def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    del current_user
    return [_category_read(item) for item in db.query(TemplateCategory).order_by(TemplateCategory.sort_order, TemplateCategory.name).all()]


@router.post("/categories", response_model=TemplateCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: TemplateCategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="分类名称不能为空")
    if db.query(TemplateCategory).filter(func.lower(TemplateCategory.name) == name.lower()).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="分类名称已存在")
    category = TemplateCategory(name=name, sort_order=payload.sort_order, created_by_id=current_user.id, updated_by_id=current_user.id)
    db.add(category)
    db.commit()
    db.refresh(category)
    return _category_read(category)


@router.patch("/categories/{category_id}", response_model=TemplateCategoryRead)
def update_category(
    category_id: int,
    payload: TemplateCategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    category = _category_or_404(db, category_id)
    name = payload.name.strip()
    duplicate = db.query(TemplateCategory).filter(func.lower(TemplateCategory.name) == name.lower(), TemplateCategory.id != category_id).first()
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="分类名称已存在")
    category.name = name
    category.sort_order = payload.sort_order
    category.updated_by_id = current_user.id
    db.commit()
    db.refresh(category)
    return _category_read(category)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    del current_user
    category = _category_or_404(db, category_id)
    db.query(TemplateLibraryItem).filter(TemplateLibraryItem.category_id == category.id).update({"category_id": None}, synchronize_session=False)
    db.delete(category)
    db.commit()


@router.get("/templates", response_model=list[TemplateItemRead])
def list_templates(
    category_id: int | None = Query(default=None, gt=0),
    q: str = Query(default="", max_length=160),
    sort: Literal["updated", "name"] = Query(default="updated"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    del current_user
    query = db.query(TemplateLibraryItem)
    if category_id is not None:
        query = query.filter(TemplateLibraryItem.category_id == category_id)
    if q.strip():
        query = query.filter(TemplateLibraryItem.name.ilike(f"%{q.strip()}%"))
    order = (
        (TemplateLibraryItem.name.asc(), TemplateLibraryItem.id.desc())
        if sort == "name"
        else (TemplateLibraryItem.updated_at.desc(), TemplateLibraryItem.id.desc())
    )
    return [template_payload(item) for item in query.order_by(*order).all()]


@router.get("/templates/{template_id}", response_model=TemplateItemRead)
def get_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    del current_user
    return template_payload(_template_or_404(db, template_id))


async def _write_template(
    db: Session,
    template: TemplateLibraryItem,
    *,
    name: str,
    category_id: int | None,
    html: str,
    source_type: str,
    user_id: int,
) -> TemplateLibraryItem:
    clean_name = name.strip()
    if not clean_name:
        raise TemplateLibraryError("模板名称不能为空")
    category_or_error(db, category_id)
    rendered_html, warnings = await localize_template_html(db, template, html)
    template.name = clean_name
    template.category_id = category_id
    template.html = rendered_html
    template.source_type = TemplateSourceType(source_type)
    template.image_warnings_json = json.dumps(warnings, ensure_ascii=False, separators=(",", ":"))
    template.updated_by_id = user_id
    remove_unreferenced_assets(db, template, rendered_html)
    return template


@router.post("/templates", response_model=TemplateItemRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    template = TemplateLibraryItem(name=payload.name.strip() or "未命名模板", html="", source_type=TemplateSourceType(payload.source_type), created_by_id=current_user.id, updated_by_id=current_user.id)
    db.add(template)
    db.flush()
    try:
        await _write_template(db, template, name=payload.name, category_id=payload.category_id, html=payload.html, source_type=payload.source_type, user_id=current_user.id)
        db.commit()
        db.refresh(template)
        return template_payload(template)
    except TemplateLibraryError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.patch("/templates/{template_id}", response_model=TemplateItemRead)
async def update_template(
    template_id: int,
    payload: TemplateItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    template = _template_or_404(db, template_id)
    try:
        await _write_template(db, template, name=payload.name, category_id=payload.category_id, html=payload.html, source_type=payload.source_type, user_id=current_user.id)
        db.commit()
        db.refresh(template)
        return template_payload(template)
    except TemplateLibraryError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    del current_user
    template = _template_or_404(db, template_id)
    for asset in db.query(TemplateImageAsset).filter(TemplateImageAsset.template_id == template.id).all():
        delete_asset_object(db, asset)
        # SQLite's foreign-key cascade is not guaranteed to be enabled for
        # every deployment connection. Remove the row explicitly so the
        # durable asset record cannot outlive its template.
        db.delete(asset)
    db.delete(template)
    db.commit()


@router.get("/assets/{asset_id}")
def get_template_asset(asset_id: str, db: Session = Depends(get_db)) -> Response:
    asset = db.get(TemplateImageAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板图片不存在")
    try:
        data = read_asset_bytes(db, asset)
    except TemplateLibraryError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板图片不存在") from None
    return Response(data, media_type=asset.content_type, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=86400"})


@router.post("/generations", response_model=TemplateGenerationRead, status_code=status.HTTP_202_ACCEPTED)
async def create_generation(
    payload: TemplateGenerationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    model = db.get(AIModel, payload.model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该模型的权限")
    generation = TemplateGeneration(id=str(uuid4()), model_id=model.id, user_id=current_user.id, prompt=payload.prompt.strip())
    db.add(generation)
    db.commit()
    db.refresh(generation)
    start_generation(generation.id)
    return generation_payload(generation)


@router.get("/generations/{generation_id}", response_model=TemplateGenerationRead)
def get_generation(
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    generation = db.get(TemplateGeneration, generation_id)
    if generation is None or generation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板生成任务不存在")
    return generation_payload(generation)


@router.post("/generations/{generation_id}/cancel", response_model=TemplateGenerationRead)
def cancel_generation(
    generation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    generation = db.get(TemplateGeneration, generation_id)
    if generation is None or generation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板生成任务不存在")
    if generation.status in {TemplateGenerationStatus.PENDING, TemplateGenerationStatus.RUNNING}:
        generation.cancel_requested = True
        db.commit()
        db.refresh(generation)
    return generation_payload(generation)


@router.post("/generations/{generation_id}/save", response_model=TemplateItemRead, status_code=status.HTTP_201_CREATED)
async def save_generation(
    generation_id: str,
    payload: TemplateGenerationSave,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    generation = db.get(TemplateGeneration, generation_id)
    if generation is None or generation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板生成任务不存在")
    if generation.status != TemplateGenerationStatus.SUCCEEDED or not generation.output_html:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="模板生成尚未完成或结果不可用")
    template = TemplateLibraryItem(name=payload.name.strip() or "未命名模板", html="", source_type=TemplateSourceType.AI, created_by_id=current_user.id, updated_by_id=current_user.id)
    db.add(template)
    db.flush()
    try:
        await _write_template(db, template, name=payload.name, category_id=payload.category_id, html=generation.output_html, source_type="ai", user_id=current_user.id)
        generation.status = TemplateGenerationStatus.SAVED
        db.commit()
        db.refresh(template)
        return template_payload(template)
    except TemplateLibraryError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
