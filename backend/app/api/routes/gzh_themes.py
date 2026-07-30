import json
from html import escape

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.document import Document
from app.models.ai_model import AIModel
from app.models.gzh_theme import (
    GzhTheme,
    GzhThemeGeneration,
    GzhThemeGenerationStatus,
    GzhThemeReferenceAsset,
    GzhThemeStatus,
    GzhThemeVersion,
    GzhThemeVersionStatus,
)
from app.models.gzh_theme_proposal import GzhThemeProposal
from app.models.chat_session import ChatSession
from app.models.user import User, UserRole
from app.schemas.gzh_theme import (
    GzhThemeCreate,
    GzhThemeGenerationCreate,
    GzhThemeGenerationRead,
    GzhThemeGenerationSave,
    GzhThemeManagerRead,
    GzhThemeManifestRead,
    GzhThemeProposalCreate,
    GzhThemeProposalRead,
    GzhThemePublishRead,
    GzhThemeReferenceAssetRead,
    GzhThemeRead,
    GzhThemeVersionRead,
)
from app.services.document_access import can_access_document
from app.services.gzh_theme_generation import (
    MAX_THEME_REFERENCE_BYTES,
    GzhThemeGenerationError,
    archive_theme,
    create_reference_asset,
    generation_assets,
    publish_theme_version,
    save_generation_as_draft,
    start_generation,
)
from app.services.model_access import can_access_model
from app.services.chat_session_context import bind_session_theme_proposal
from app.services.gzh_theme import (
    GzhThemeError,
    active_theme_version,
    approve_proposal,
    build_theme_manifest,
    create_proposal,
    lint_theme_source,
    list_themes,
    manifest_payload,
    theme_manifest,
    preview_html,
    validate_gzh_html,
)


router = APIRouter(prefix="/api", tags=["gzh-themes"])


def _theme_read(theme) -> GzhThemeRead:
    return GzhThemeRead(
        id=theme.id,
        key=theme.key,
        name=theme.name,
        description=theme.description,
        scenarios=theme.scenarios,
        accent_color=theme.accent_color,
        is_builtin=theme.is_builtin,
        status=theme.status,
        preview_available=bool(theme.preview_path) or theme.key.startswith("custom:"),
        active_version_id=theme.version_id,
        active_version=theme.version,
    )


def _parse_json_list(value: str) -> list[dict[str, str]]:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in payload if isinstance(item, dict)]


def _manifest_counts(value: str, source: str) -> tuple[int, int]:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not payload:
        try:
            from app.services.gzh_theme import build_theme_manifest, manifest_payload

            payload = manifest_payload(build_theme_manifest(source))
        except GzhThemeError:
            payload = {}
    return len(payload.get("components", [])), len(payload.get("recipes", []))


def _version_read(version: GzhThemeVersion) -> GzhThemeVersionRead:
    components, recipes = _manifest_counts(version.manifest_json, version.source_markdown)
    return GzhThemeVersionRead(
        id=version.id,
        theme_id=version.theme_id,
        version=version.version,
        status=version.status.value,
        generation_brief=version.generation_brief,
        validation=_parse_json_list(version.validation_json),
        component_count=components,
        recipe_count=recipes,
        created_at=version.created_at,
        published_at=version.published_at,
    )


def _custom_theme_read(db: Session, theme: GzhTheme) -> GzhThemePublishRead:
    version = active_theme_version(db, theme)
    return GzhThemePublishRead(
        id=theme.id,
        key=f"custom:{theme.id}",
        name=theme.name,
        description=theme.description,
        scenarios=[item for item in theme.scenarios.split("\n") if item],
        accent_color=theme.accent_color,
        is_builtin=False,
        preview_available=bool(version.preview_html if version else theme.preview_html),
        status=theme.status.value,
        active_version_id=version.id if version else None,
        active_version=version.version if version else None,
    )


def _manager_theme_read(db: Session, theme: GzhTheme) -> GzhThemeManagerRead:
    versions = (
        db.query(GzhThemeVersion)
        .filter(GzhThemeVersion.theme_id == theme.id)
        .order_by(GzhThemeVersion.version.desc())
        .all()
    )
    return GzhThemeManagerRead(
        **_custom_theme_read(db, theme).model_dump(),
        versions=[_version_read(item) for item in versions],
    )


def _generation_read(generation: GzhThemeGeneration) -> GzhThemeGenerationRead:
    try:
        output = json.loads(generation.output_json or "{}")
    except json.JSONDecodeError:
        output = {}
    manifest = output.get("manifest") if isinstance(output.get("manifest"), dict) else {}
    return GzhThemeGenerationRead(
        id=generation.id,
        status=generation.status.value,
        theme_id=generation.theme_id,
        name_hint=generation.name_hint,
        slug_hint=generation.slug_hint,
        brief=generation.brief,
        validation=_parse_json_list(generation.validation_json),
        error_message=generation.error_message,
        preview_html=str(output.get("preview_html") or "") if generation.status in {GzhThemeGenerationStatus.SUCCEEDED, GzhThemeGenerationStatus.SAVED} else "",
        component_count=len(manifest.get("components", [])),
        recipe_count=len(manifest.get("recipes", [])),
        created_at=generation.created_at,
        finished_at=generation.finished_at,
    )


def _proposal_read(proposal: GzhThemeProposal) -> GzhThemeProposalRead:
    try:
        selected_component_ids = json.loads(proposal.selected_component_ids_json or "[]")
    except json.JSONDecodeError:
        selected_component_ids = []
    return GzhThemeProposalRead(
        id=proposal.id,
        theme_key=proposal.theme_key,
        theme_name=proposal.theme_name,
        apply_mode=proposal.apply_mode,
        user_instructions=proposal.user_instructions,
        article_type=proposal.article_type,
        recipe_id=proposal.recipe_id,
        selected_component_ids=[str(item) for item in selected_component_ids if isinstance(item, str)],
        status=proposal.status.value,
        expires_at=proposal.expires_at,
    )


@router.get("/gzh-themes", response_model=list[GzhThemeRead])
def list_gzh_themes(
    include_drafts: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GzhThemeRead]:
    if include_drafts and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可查看未发布主题")
    try:
        return [_theme_read(theme) for theme in list_themes(db, include_drafts=include_drafts)]
    except GzhThemeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/gzh-theme-manager", response_model=list[GzhThemeManagerRead])
def list_managed_gzh_themes(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[GzhThemeManagerRead]:
    themes = db.query(GzhTheme).order_by(GzhTheme.updated_at.desc()).all()
    return [_manager_theme_read(db, item) for item in themes]


@router.post("/gzh-theme-assets", response_model=GzhThemeReferenceAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_gzh_theme_reference_asset(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemeReferenceAssetRead:
    asset: GzhThemeReferenceAsset | None = None
    try:
        data = await file.read(MAX_THEME_REFERENCE_BYTES + 1)
        asset = create_reference_asset(db, uploader_id=current_user.id, data=data, filename=file.filename or "reference")
        db.commit()
        db.refresh(asset)
        return GzhThemeReferenceAssetRead(
            id=asset.id,
            filename=asset.filename,
            content_type=asset.content_type,
            size=asset.size,
            expires_at=asset.expires_at,
        )
    except GzhThemeGenerationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post("/gzh-theme-generations", response_model=GzhThemeGenerationRead, status_code=status.HTTP_202_ACCEPTED)
async def create_gzh_theme_generation(
    payload: GzhThemeGenerationCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemeGenerationRead:
    model = db.get(AIModel, payload.model_id)
    if not model or not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 模型不存在或不可用")
    theme = db.get(GzhTheme, payload.theme_id) if payload.theme_id else None
    if payload.theme_id and not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待调整主题不存在")
    generation = GzhThemeGeneration(
        id=__import__("uuid").uuid4().hex,
        theme_id=theme.id if theme else None,
        base_version_id=theme.active_version_id if theme else None,
        model_id=model.id,
        user_id=current_user.id,
        name_hint=payload.name_hint.strip(),
        slug_hint=payload.slug_hint.strip().lower(),
        accent_color=payload.accent_color.strip(),
        scenarios_json=json.dumps([item.strip() for item in payload.scenarios if item.strip()], ensure_ascii=False),
        brief=payload.brief.strip(),
        reference_asset_ids_json=json.dumps(payload.reference_asset_ids, ensure_ascii=False),
        status=GzhThemeGenerationStatus.PENDING,
    )
    db.add(generation)
    try:
        # Validate ownership and model capability before accepting a long task.
        assets = generation_assets(db, generation)
        if assets and not model.is_multimodal:
            raise GzhThemeGenerationError("当前模型不支持参考图，请更换多模态模型或移除图片")
        db.commit()
        db.refresh(generation)
    except GzhThemeGenerationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    start_generation(generation.id)
    return _generation_read(generation)


@router.get("/gzh-theme-generations/{generation_id}", response_model=GzhThemeGenerationRead)
def get_gzh_theme_generation(
    generation_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemeGenerationRead:
    generation = db.get(GzhThemeGeneration, generation_id)
    if not generation or generation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题生成任务不存在")
    return _generation_read(generation)


@router.post("/gzh-theme-generations/{generation_id}/cancel", response_model=GzhThemeGenerationRead)
def cancel_gzh_theme_generation(
    generation_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemeGenerationRead:
    generation = db.get(GzhThemeGeneration, generation_id)
    if not generation or generation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题生成任务不存在")
    if generation.status in {GzhThemeGenerationStatus.PENDING, GzhThemeGenerationStatus.RUNNING}:
        generation.cancel_requested = True
        if generation.status == GzhThemeGenerationStatus.PENDING:
            generation.status = GzhThemeGenerationStatus.CANCELLED
        db.commit()
        db.refresh(generation)
    return _generation_read(generation)


@router.post("/gzh-theme-generations/{generation_id}/save", response_model=GzhThemeManagerRead)
def save_gzh_theme_generation(
    generation_id: str,
    payload: GzhThemeGenerationSave,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemeManagerRead:
    generation = db.get(GzhThemeGeneration, generation_id)
    if not generation or generation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题生成任务不存在")
    if payload.name.strip():
        generation.name_hint = payload.name.strip()
    if payload.slug.strip():
        generation.slug_hint = payload.slug.strip().lower()
    if payload.accent_color.strip():
        generation.accent_color = payload.accent_color.strip()
    if payload.scenarios:
        generation.scenarios_json = json.dumps([item.strip() for item in payload.scenarios if item.strip()], ensure_ascii=False)
    try:
        theme, _ = save_generation_as_draft(db, generation)
        if payload.description.strip():
            theme.description = payload.description.strip()
        db.commit()
        db.refresh(theme)
        return _manager_theme_read(db, theme)
    except GzhThemeGenerationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/gzh-theme-versions/{version_id}/preview")
def get_gzh_theme_version_preview(
    version_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    version = db.get(GzhThemeVersion, version_id)
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题版本不存在")
    return {"html": version.preview_html}


@router.post("/gzh-theme-versions/{version_id}/publish", response_model=GzhThemeManagerRead)
def publish_gzh_theme_version(
    version_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemeManagerRead:
    version = db.get(GzhThemeVersion, version_id)
    theme = db.get(GzhTheme, version.theme_id) if version else None
    if not version or not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题版本不存在")
    try:
        publish_theme_version(db, theme, version)
        db.commit()
        db.refresh(theme)
        return _manager_theme_read(db, theme)
    except GzhThemeGenerationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/gzh-themes/{theme_id}/archive", response_model=GzhThemeManagerRead)
def archive_gzh_theme(
    theme_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemeManagerRead:
    theme = db.get(GzhTheme, theme_id)
    if not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    archive_theme(db, theme)
    db.commit()
    db.refresh(theme)
    return _manager_theme_read(db, theme)


@router.get("/gzh-themes/{theme_key:path}/preview")
def get_gzh_theme_preview(theme_key: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        return {"html": preview_html(db, theme_key, include_drafts=current_user.role == UserRole.ADMIN)}
    except GzhThemeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/gzh-themes/{theme_key:path}/manifest", response_model=GzhThemeManifestRead)
def get_gzh_theme_manifest(
    theme_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GzhThemeManifestRead:
    try:
        return GzhThemeManifestRead.model_validate(
            theme_manifest(db, theme_key, include_drafts=current_user.role == UserRole.ADMIN)
        )
    except GzhThemeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/documents/{document_id}/gzh-theme-proposals", response_model=GzhThemeProposalRead, status_code=status.HTTP_201_CREATED)
def create_gzh_theme_proposal(
    document_id: int,
    payload: GzhThemeProposalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GzhThemeProposalRead:
    document = db.get(Document, document_id)
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if payload.session_id is not None:
        chat_session = db.get(ChatSession, payload.session_id)
        if not chat_session or chat_session.document_id != document.id or chat_session.is_archived:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="对话不存在或已归档")
    try:
        proposal = create_proposal(
            db,
            document_id=document.id,
            session_id=payload.session_id,
            user_id=current_user.id,
            current_html=document.current_html,
            theme_key=payload.theme_key,
            apply_mode=payload.apply_mode,
            user_instructions=payload.user_instructions,
            article_type=payload.article_type,
            recipe_id=payload.recipe_id,
            selected_component_ids=payload.selected_component_ids,
        )
        db.commit()
        db.refresh(proposal)
        return _proposal_read(proposal)
    except GzhThemeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/documents/{document_id}/gzh-theme-proposals/{proposal_id}/approve", response_model=GzhThemeProposalRead)
def approve_gzh_theme_proposal(
    document_id: int,
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GzhThemeProposalRead:
    document = db.get(Document, document_id)
    proposal = db.get(GzhThemeProposal, proposal_id)
    if not document or not proposal or proposal.document_id != document_id or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题提案不存在")
    try:
        approve_proposal(db, proposal, document.current_html, current_user.id)
        if proposal.session_id is not None:
            chat_session = db.get(ChatSession, proposal.session_id)
            if not chat_session or chat_session.document_id != document.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="主题提案关联的对话不存在")
            bind_session_theme_proposal(db, chat_session.id, proposal.id)
        db.commit()
        db.refresh(proposal)
        return _proposal_read(proposal)
    except GzhThemeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/gzh-themes", response_model=GzhThemePublishRead, status_code=status.HTTP_201_CREATED)
def create_custom_gzh_theme(
    payload: GzhThemeCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemePublishRead:
    existing = db.query(GzhTheme).filter(GzhTheme.slug == payload.slug).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="主题标识已存在")
    try:
        lint_errors = [
            item["message"]
            for item in lint_theme_source(payload.source_markdown)
            if item["level"] == "ERROR"
        ]
    except GzhThemeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if lint_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="自定义主题组件库检查未通过：" + "；".join(lint_errors),
        )
    preview = payload.preview_html.strip() or (
        f'<section style="padding:24px;border-top:3px solid {payload.accent_color};">'
        '<p style="margin:0 0 8px;font-size:12px;font-weight:700;"><span leaf="">CUSTOM THEME</span></p>'
        f'<h2 style="margin:0;font-size:22px;"><span leaf="">{escape(payload.name)}</span></h2>'
        '</section>'
    )
    try:
        strict = validate_gzh_html(preview)
    except GzhThemeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if strict["hasError"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="预览 HTML 严格检查未通过：" + "；".join(strict["errors"]))
    theme = GzhTheme(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        scenarios="\n".join(item.strip() for item in payload.scenarios if item.strip()),
        accent_color=payload.accent_color,
        source_markdown=payload.source_markdown,
        preview_html=preview,
        status=GzhThemeStatus.DRAFT,
        created_by_id=current_user.id,
    )
    db.add(theme)
    db.flush()
    manifest = manifest_payload(build_theme_manifest(payload.source_markdown))
    version = GzhThemeVersion(
        theme_id=theme.id,
        version=1,
        generation_brief="高级导入",
        source_markdown=payload.source_markdown,
        preview_html=preview,
        manifest_json=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        validation_json=json.dumps([*lint_theme_source(payload.source_markdown), {"level": "INFO", "message": "高级导入严格检查通过"}], ensure_ascii=False),
        status=GzhThemeVersionStatus.DRAFT,
        created_by_id=current_user.id,
    )
    db.add(version)
    db.flush()
    theme.active_version_id = version.id
    db.commit()
    db.refresh(theme)
    return _custom_theme_read(db, theme)


@router.post("/gzh-themes/{theme_id}/publish", response_model=GzhThemePublishRead)
def publish_custom_gzh_theme(
    theme_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> GzhThemePublishRead:
    theme = db.get(GzhTheme, theme_id)
    if not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    version = active_theme_version(db, theme)
    if not version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="主题没有可发布的草稿版本")
    if theme.status != GzhThemeStatus.DRAFT or version.status != GzhThemeVersionStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有草稿主题可以发布")
    try:
        publish_theme_version(db, theme, version)
    except GzhThemeGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    db.refresh(theme)
    return _custom_theme_read(db, theme)
