import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import desc
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.chat_message import ChatMessage, MessageRole
from app.models.document import Document, DocumentSourceType
from app.models.document_group import DocumentGroup
from app.models.document_import import DocumentImport, DocumentImportAsset, DocumentImportStatus
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.storage_config import StorageConfig
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole
from app.models.user_group import UserGroup
from app.schemas.document import (
    DocumentCreate,
    DocumentDetail,
    DocumentImageUpload,
    DocumentImportAssetCreate,
    DocumentImportAssetUpload,
    DocumentImportAssetsCreate,
    DocumentImportAssetsResult,
    DocumentImportComplete,
    DocumentImportCreate,
    DocumentImportCreateResult,
    DocumentImportStatusRead,
    DocumentSourceAccess,
    DocumentSummary,
    DocumentUpdate,
    DocumentVersionDetail,
    DocumentVersionSummary,
    VisibilityTargetsRead,
)
from app.schemas.chat import ChatRevertRequest
from app.services import oss_client
from app.services.document_access import accessible_documents_query, can_access_document, can_access_document_group
from app.services.document_activity import touch_document, touch_group
from app.services.document_versions import create_document_version

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_IMPORT_FILE_SIZE = 30 * 1024 * 1024
MAX_REPLACEMENT_IMAGE_SIZE = 10 * 1024 * 1024
REPLACEABLE_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "avif", "bmp"}
IMPORT_IMAGE_EXTENSIONS = REPLACEABLE_IMAGE_EXTENSIONS | {"svg"}
IMPORT_SESSION_TTL = timedelta(hours=24)
IMPORT_UPLOAD_URL_EXPIRE_SECONDS = oss_client.DIRECT_UPLOAD_EXPIRE_SECONDS
OBJECT_VISIBILITY_RETRY_DELAYS = (0, 0.25, 0.5, 1, 2)
IMPORT_ASSET_TOKEN_PATTERN = re.compile(r"direct-import://asset/([0-9a-fA-F-]{36})")
SOURCE_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _get_accessible_document(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if not document or not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return document


def _get_accessible_group(db: Session, group_id: int, user: User) -> DocumentGroup:
    group = db.get(DocumentGroup, group_id)
    if not group or not can_access_document_group(user, group):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    return group


def _ensure_owner_or_admin(document: Document, user: User) -> None:
    if user.role != UserRole.ADMIN and document.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有创建人或管理员可以移动、删除推文")


def _configured_storage(db: Session) -> StorageConfig:
    storage = db.query(StorageConfig).first()
    if not storage or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先联系管理员在「存储设置」中配置阿里云 OSS")
    return storage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _utcnow()


def _safe_filename(filename: str, fallback: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    return name[:512] or fallback


def _source_type_for_filename(filename: str) -> tuple[DocumentSourceType, str, str]:
    safe_name = _safe_filename(filename, "上传文件")
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if ext == "pdf":
        return DocumentSourceType.PDF, ext, SOURCE_CONTENT_TYPES[ext]
    if ext == "docx":
        return DocumentSourceType.WORD, ext, SOURCE_CONTENT_TYPES[ext]
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传 PDF 或 Word(.docx) 文件")


def _source_upload_target(storage: StorageConfig, import_session: DocumentImport) -> dict[str, str | int]:
    return {
        "object_key": import_session.source_object_key,
        "content_type": import_session.source_content_type,
        "upload_url": oss_client.sign_direct_upload(
            storage, import_session.source_object_key, import_session.source_content_type
        ),
        "expires_in_seconds": IMPORT_UPLOAD_URL_EXPIRE_SECONDS,
    }


def _asset_upload_target(storage: StorageConfig, asset: DocumentImportAsset) -> dict[str, str | int]:
    return {
        "object_key": asset.object_key,
        "content_type": asset.content_type,
        "upload_url": oss_client.sign_direct_upload(storage, asset.object_key, asset.content_type),
        "expires_in_seconds": IMPORT_UPLOAD_URL_EXPIRE_SECONDS,
    }


def _get_import_session(db: Session, import_id: str, user: User) -> DocumentImport:
    import_session = (
        db.query(DocumentImport)
        .options(selectinload(DocumentImport.assets))
        .filter(DocumentImport.id == import_id)
        .first()
    )
    if not import_session or import_session.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导入任务不存在")
    return import_session


def _require_pending_import(import_session: DocumentImport, db: Session) -> None:
    if import_session.status == DocumentImportStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该导入任务已完成")
    if import_session.status == DocumentImportStatus.EXPIRED or _is_expired(import_session.expires_at):
        if import_session.status != DocumentImportStatus.EXPIRED:
            import_session.status = DocumentImportStatus.EXPIRED
            db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="导入任务已过期，请重新选择文件")


def _expire_stale_imports(db: Session, storage: StorageConfig) -> None:
    """Best-effort cleanup for abandoned direct uploads; completed assets are never removed."""
    stale_imports = (
        db.query(DocumentImport)
        .options(selectinload(DocumentImport.assets))
        .filter(DocumentImport.status == DocumentImportStatus.PENDING, DocumentImport.expires_at < _utcnow())
        .all()
    )
    if not stale_imports:
        return
    for import_session in stale_imports:
        for object_key in [import_session.source_object_key, *(asset.object_key for asset in import_session.assets)]:
            try:
                oss_client.delete_object(storage, object_key)
            except Exception:  # Object may never have been uploaded or have been removed by an OSS lifecycle rule.
                pass
        import_session.status = DocumentImportStatus.EXPIRED
    db.commit()


def _validate_uploaded_object(storage: StorageConfig, object_key: str, content_type: str, size: int, label: str) -> None:
    last_error: Exception | None = None
    for delay in OBJECT_VISIBILITY_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            metadata = oss_client.inspect_object(storage, object_key)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
        actual_type = str(metadata["content_type"]).lower()
        if int(metadata["size"]) == size and actual_type == content_type.lower():
            return
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{label}的大小或类型校验失败，请重新上传")
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{label}正在同步到 OSS，请稍候自动重试") from last_error


def _get_users(db: Session, user_ids: list[int]) -> list[User]:
    unique_ids = list(dict.fromkeys(user_ids))
    if not unique_ids:
        return []
    users = db.query(User).filter(User.id.in_(unique_ids)).all()
    if len(users) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户")
    users_by_id = {user.id: user for user in users}
    return [users_by_id[user_id] for user_id in unique_ids]


def _get_user_groups(db: Session, group_ids: list[int]) -> list[UserGroup]:
    unique_ids = list(dict.fromkeys(group_ids))
    if not unique_ids:
        return []
    groups = db.query(UserGroup).filter(UserGroup.id.in_(unique_ids)).all()
    if len(groups) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户组")
    groups_by_id = {group.id: group for group in groups}
    return [groups_by_id[group_id] for group_id in unique_ids]


def _apply_visibility(
    resource: Document | DocumentGroup,
    db: Session,
    visibility_mode: str,
    allowed_user_ids: list[int] | None,
    allowed_group_ids: list[int] | None,
) -> None:
    resource.visibility_mode = VisibilityMode(visibility_mode)
    if resource.visibility_mode == VisibilityMode.ALL:
        resource.allowed_users = []
        resource.allowed_groups = []
        return
    if allowed_user_ids is not None:
        resource.allowed_users = _get_users(db, allowed_user_ids)
    if allowed_group_ids is not None:
        resource.allowed_groups = _get_user_groups(db, allowed_group_ids)


@router.get("", response_model=list[DocumentSummary])
def list_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Document]:
    return (
        accessible_documents_query(db.query(Document), current_user)
        .options(
            selectinload(Document.created_by),
            selectinload(Document.last_modified_by),
            selectinload(Document.allowed_users),
            selectinload(Document.allowed_groups),
        )
        .order_by(desc(Document.updated_at))
        .all()
    )


@router.get("/visibility-targets", response_model=VisibilityTargetsRead)
def get_visibility_targets(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, list[User] | list[UserGroup]]:
    """仅提供可见性配置所需的基础身份信息，不返回用户组成员列表。"""
    return {
        "users": db.query(User).filter(User.is_active.is_(True)).order_by(User.display_name, User.username).all(),
        "groups": db.query(UserGroup).order_by(UserGroup.name, UserGroup.id).all(),
    }


@router.post("/imports", response_model=DocumentImportCreateResult, status_code=status.HTTP_201_CREATED)
def create_direct_import(
    payload: DocumentImportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImportCreateResult:
    source_type, extension, expected_content_type = _source_type_for_filename(payload.filename)
    if payload.size > MAX_IMPORT_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件过大，请上传 30MB 以内的文件")
    if payload.content_type.lower() not in {expected_content_type, "application/octet-stream"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件类型与扩展名不匹配")

    storage = _configured_storage(db)
    _expire_stale_imports(db, storage)
    import_id = str(uuid4())
    import_session = DocumentImport(
        id=import_id,
        owner_id=current_user.id,
        source_type=source_type,
        source_filename=_safe_filename(payload.filename, "上传文件"),
        source_content_type=expected_content_type,
        source_size=payload.size,
        source_object_key=f"yibanpaiban/direct-imports/{import_id}/source.{extension}",
        expires_at=_utcnow() + IMPORT_SESSION_TTL,
    )
    db.add(import_session)
    db.commit()
    db.refresh(import_session)
    return DocumentImportCreateResult(
        id=import_session.id,
        source_type=import_session.source_type,
        source_upload=_source_upload_target(storage, import_session),
        expires_at=import_session.expires_at,
    )


@router.get("/imports/{import_id}", response_model=DocumentImportStatusRead)
def get_direct_import(
    import_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImportStatusRead:
    import_session = _get_import_session(db, import_id, current_user)
    if import_session.status == DocumentImportStatus.PENDING and _is_expired(import_session.expires_at):
        import_session.status = DocumentImportStatus.EXPIRED
        db.commit()

    if import_session.status != DocumentImportStatus.PENDING:
        return DocumentImportStatusRead(
            id=import_session.id,
            status=import_session.status.value,
            source_upload=None,
            expires_at=import_session.expires_at,
            document_id=import_session.document_id,
        )

    storage = _configured_storage(db)
    assets = [
        DocumentImportAssetUpload(
            client_id=asset.client_id,
            asset_id=asset.id,
            upload=_asset_upload_target(storage, asset),
        )
        for asset in import_session.assets
    ]
    return DocumentImportStatusRead(
        id=import_session.id,
        status=import_session.status.value,
        source_upload=_source_upload_target(storage, import_session),
        assets=assets,
        expires_at=import_session.expires_at,
        document_id=import_session.document_id,
    )


@router.post("/imports/{import_id}/assets", response_model=DocumentImportAssetsResult)
def create_direct_import_assets(
    import_id: str,
    payload: DocumentImportAssetsCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImportAssetsResult:
    import_session = _get_import_session(db, import_id, current_user)
    _require_pending_import(import_session, db)
    client_ids = [asset.client_id for asset in payload.assets]
    if len(client_ids) != len(set(client_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片标识不能重复")

    storage = _configured_storage(db)
    existing_by_client_id = {asset.client_id: asset for asset in import_session.assets}
    created_assets: list[DocumentImportAsset] = []
    for metadata in payload.assets:
        filename = _safe_filename(metadata.filename, "image")
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        content_type = metadata.content_type.lower().split(";", 1)[0]
        if (
            extension not in IMPORT_IMAGE_EXTENSIONS
            or not content_type.startswith("image/")
            or metadata.size > MAX_REPLACEMENT_IMAGE_SIZE
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="仅支持不超过 10MB 的 JPG、PNG、GIF、WebP、AVIF、BMP 或 SVG 图片",
            )
        existing = existing_by_client_id.get(metadata.client_id)
        if existing:
            if existing.size != metadata.size or existing.content_type != content_type:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="图片标识已被用于不同文件")
            created_assets.append(existing)
            continue
        asset_id = str(uuid4())
        asset = DocumentImportAsset(
            id=asset_id,
            import_id=import_session.id,
            client_id=metadata.client_id,
            filename=filename,
            content_type=content_type,
            size=metadata.size,
            object_key=f"yibanpaiban/direct-imports/{import_session.id}/assets/{asset_id}.{extension}",
        )
        db.add(asset)
        created_assets.append(asset)
    db.commit()
    return DocumentImportAssetsResult(
        assets=[
            DocumentImportAssetUpload(
                client_id=asset.client_id,
                asset_id=asset.id,
                upload=_asset_upload_target(storage, asset),
            )
            for asset in created_assets
        ]
    )


@router.post("/imports/{import_id}/complete", response_model=DocumentDetail)
def complete_direct_import(
    import_id: str,
    payload: DocumentImportComplete,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    import_session = _get_import_session(db, import_id, current_user)
    if import_session.status == DocumentImportStatus.COMPLETED:
        if import_session.document_id:
            document = db.get(Document, import_session.document_id)
            if document:
                return document
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="导入任务状态异常")
    _require_pending_import(import_session, db)
    storage = _configured_storage(db)
    _validate_uploaded_object(
        storage,
        import_session.source_object_key,
        import_session.source_content_type,
        import_session.source_size,
        "源文件",
    )

    assets_by_id = {asset.id: asset for asset in import_session.assets}
    referenced_asset_ids = set(IMPORT_ASSET_TOKEN_PATTERN.findall(payload.html))
    if referenced_asset_ids != set(assets_by_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="解析图片清单与正文占位符不一致")

    html = payload.html
    for asset_id, asset in assets_by_id.items():
        _validate_uploaded_object(storage, asset.object_key, asset.content_type, asset.size, "解析图片")
        html = html.replace(
            f"direct-import://asset/{asset_id}",
            oss_client.sign_read_url(storage, asset.object_key, oss_client.IMAGE_URL_EXPIRE_SECONDS),
        )
    if "direct-import://asset/" in html:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="正文存在未授权的图片占位符")

    group = _get_accessible_group(db, payload.group_id, current_user) if payload.group_id is not None else None
    default_title = import_session.source_filename.rsplit(".", 1)[0] or import_session.source_filename
    document = Document(
        owner_id=current_user.id,
        group_id=group.id if group else None,
        created_by_id=current_user.id,
        last_modified_by_id=current_user.id,
        title=(payload.title or default_title)[:256],
        current_html=html,
        source_type=import_session.source_type,
        source_object_key=import_session.source_object_key,
        source_filename=import_session.source_filename,
        source_content_type=import_session.source_content_type,
        source_size=import_session.source_size,
    )
    db.add(document)
    db.flush()
    create_document_version(db, document, current_user.id, DocumentVersionSource.INITIAL, "前端直传导入")
    if group:
        touch_group(group, current_user.id)
    import_session.status = DocumentImportStatus.COMPLETED
    import_session.document_id = document.id
    db.commit()
    db.refresh(document)
    return document


@router.post("", response_model=DocumentDetail)
def create_document(
    payload: DocumentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Document:
    group = _get_accessible_group(db, payload.group_id, current_user) if payload.group_id is not None else None
    document = Document(
        owner_id=current_user.id,
        group_id=group.id if group else None,
        created_by_id=current_user.id,
        last_modified_by_id=current_user.id,
        title=payload.title,
        current_html="",
        source_type=DocumentSourceType.BLANK,
        visibility_mode=VisibilityMode(payload.visibility_mode),
    )
    _apply_visibility(document, db, payload.visibility_mode, payload.allowed_user_ids, payload.allowed_group_ids)
    db.add(document)
    db.flush()
    create_document_version(db, document, current_user.id, DocumentVersionSource.INITIAL, "创建空白文档")
    if group:
        touch_group(group, current_user.id)
    db.commit()
    db.refresh(document)
    return document


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Document:
    return _get_accessible_document(db, document_id, current_user)


@router.get("/{document_id}/source-access", response_model=DocumentSourceAccess)
def get_document_source_access(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSourceAccess:
    document = _get_accessible_document(db, document_id, current_user)
    if not document.has_source_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该文档没有可查看的原始文件")
    storage = _configured_storage(db)
    return DocumentSourceAccess(
        filename=document.source_filename or "source",
        content_type=document.source_content_type or "application/octet-stream",
        size=document.source_size or 0,
        url=oss_client.sign_read_url(storage, document.source_object_key or ""),
        expires_in_seconds=oss_client.MANAGEMENT_URL_EXPIRE_SECONDS,
    )


@router.patch("/{document_id}", response_model=DocumentDetail)
def update_document(
    document_id: int,
    payload: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    document = _get_accessible_document(db, document_id, current_user)
    changed = False
    version_changed = False
    if payload.title is not None:
        if document.title != payload.title:
            document.title = payload.title
            changed = True
            version_changed = True
    if payload.current_html is not None:
        if document.current_html != payload.current_html:
            document.current_html = payload.current_html
            changed = True
            version_changed = True
    if "group_id" in payload.model_fields_set and document.group_id != payload.group_id:
        _ensure_owner_or_admin(document, current_user)
        old_group = document.group
        new_group = _get_accessible_group(db, payload.group_id, current_user) if payload.group_id is not None else None
        document.group = new_group
        if old_group:
            touch_group(old_group, current_user.id)
        if new_group:
            touch_group(new_group, current_user.id)
        changed = True
    visibility_fields = {"visibility_mode", "allowed_user_ids", "allowed_group_ids"}
    if visibility_fields.intersection(payload.model_fields_set):
        _ensure_owner_or_admin(document, current_user)
        visibility_mode = payload.visibility_mode or document.visibility_mode.value
        _apply_visibility(document, db, visibility_mode, payload.allowed_user_ids, payload.allowed_group_ids)
        changed = True
    if changed:
        touch_document(document, current_user.id)
    if version_changed:
        create_document_version(db, document, current_user.id, DocumentVersionSource.MANUAL, "手动保存")
    db.commit()
    db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    document = _get_accessible_document(db, document_id, current_user)
    _ensure_owner_or_admin(document, current_user)
    db.delete(document)
    db.commit()


@router.post("/{document_id}/revert-last-ai-change", response_model=DocumentDetail)
def revert_last_ai_change(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """恢复最近一次仍在当前文档上的 AI 修改，再由用户给出新的提问。"""
    document = _get_accessible_document(db, document_id, current_user)
    message = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.role == MessageRole.ASSISTANT,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.html_before.is_not(None),
            ChatMessage.html_after.is_not(None),
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    if not message:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="没有可撤销的 AI 修改")
    if document.current_html != message.html_after:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文档已有后续手动或 AI 修改，无法安全撤销该回合；请刷新后再处理",
        )

    document.current_html = message.html_before or ""
    message.is_superseded = True
    # 移除与被撤销回答配对的用户问题，避免后续 Agent 历史出现没有回答的旧指令。
    previous_user = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.role == MessageRole.USER,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.id < message.id,
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    if previous_user:
        previous_user.is_superseded = True
    touch_document(document, current_user.id)
    db.commit()
    db.refresh(document)
    return document


@router.post("/{document_id}/images", response_model=DocumentImageUpload)
async def upload_document_image(
    document_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImageUpload:
    """上传用于替换当前排版图片的文件，返回长期可访问的 OSS 链接。"""
    _get_accessible_document(db, document_id, current_user)
    filename = file.filename or "image"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = (file.content_type or "").lower()
    if extension not in REPLACEABLE_IMAGE_EXTENSIONS or not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 JPG、PNG、GIF、WebP、AVIF 或 BMP 图片",
        )

    storage = db.query(StorageConfig).first()
    if not storage or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先联系管理员在「存储设置」中配置阿里云 OSS",
        )

    try:
        data = await file.read(MAX_REPLACEMENT_IMAGE_SIZE + 1)
        if len(data) > MAX_REPLACEMENT_IMAGE_SIZE:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="图片不能超过 10MB")
        return DocumentImageUpload(url=oss_client.upload_bytes(storage, data, filename, content_type))
    except HTTPException:
        raise
    except oss_client.OSSNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"图片上传失败: {exc}") from exc
    finally:
        await file.close()


@router.post("/{document_id}/revert-to-message", response_model=DocumentDetail)
def revert_to_message(
    document_id: int,
    payload: ChatRevertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """回退到指定用户消息之前的状态，并将该消息后的对话标记为历史分支。"""
    document = _get_accessible_document(db, document_id, current_user)
    target_message = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == payload.message_id,
            ChatMessage.document_id == document.id,
            ChatMessage.role == MessageRole.USER,
            ChatMessage.is_superseded.is_(False),
        )
        .first()
    )
    if not target_message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到可重新提问的消息")

    # 新消息均保存自身发出前的 HTML。旧数据没有该快照时，优先使用该轮 AI 的快照，
    # 再退回到此前最后一次 AI 修改后的状态，以兼容已存在的对话。
    html_before = target_message.html_before
    if html_before is None:
        following_ai = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.document_id == document.id,
                ChatMessage.role == MessageRole.ASSISTANT,
                ChatMessage.is_superseded.is_(False),
                ChatMessage.id > target_message.id,
                ChatMessage.html_before.is_not(None),
            )
            .order_by(ChatMessage.id)
            .first()
        )
        if following_ai:
            html_before = following_ai.html_before
        else:
            previous_ai = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.document_id == document.id,
                    ChatMessage.role == MessageRole.ASSISTANT,
                    ChatMessage.is_superseded.is_(False),
                    ChatMessage.id < target_message.id,
                    ChatMessage.html_after.is_not(None),
                )
                .order_by(ChatMessage.id.desc())
                .first()
            )
            if previous_ai:
                html_before = previous_ai.html_after

    if html_before is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该历史消息缺少可恢复的文档快照，无法安全回退",
        )

    latest_ai_change = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.role == MessageRole.ASSISTANT,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.id >= target_message.id,
            ChatMessage.html_after.is_not(None),
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    expected_html = latest_ai_change.html_after if latest_ai_change else html_before
    if document.current_html != expected_html:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此消息之后存在尚未处理的手动修改，无法安全回退；请先保存或刷新后再试",
        )

    document.current_html = html_before
    (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.id >= target_message.id,
        )
        .update({ChatMessage.is_superseded: True}, synchronize_session=False)
    )
    touch_document(document, current_user.id)
    db.commit()
    db.refresh(document)
    return document


@router.get("/{document_id}/versions", response_model=list[DocumentVersionSummary])
def list_document_versions(
    document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[DocumentVersion]:
    _get_accessible_document(db, document_id, current_user)
    return (
        db.query(DocumentVersion)
        .options(selectinload(DocumentVersion.created_by))
        .filter(DocumentVersion.document_id == document_id)
        .order_by(desc(DocumentVersion.version_number))
        .all()
    )


@router.get("/{document_id}/versions/{version_id}", response_model=DocumentVersionDetail)
def get_document_version(
    document_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentVersion:
    _get_accessible_document(db, document_id, current_user)
    version = (
        db.query(DocumentVersion)
        .options(selectinload(DocumentVersion.created_by))
        .filter(DocumentVersion.id == version_id, DocumentVersion.document_id == document_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    return version


@router.post("/{document_id}/versions/{version_id}/restore", response_model=DocumentDetail)
def restore_document_version(
    document_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    document = _get_accessible_document(db, document_id, current_user)
    version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.id == version_id, DocumentVersion.document_id == document_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    document.title = version.title
    document.current_html = version.html
    touch_document(document, current_user.id)
    create_document_version(
        db,
        document,
        current_user.id,
        DocumentVersionSource.RESTORE,
        f"恢复版本 v{version.version_number}",
    )
    db.commit()
    db.refresh(document)
    return document


