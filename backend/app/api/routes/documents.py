import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
import jwt
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session, selectinload

from app.api.browser_capture_upload import BrowserCaptureUploadError, read_browser_capture_upload
from app.api.deps import get_current_user
from app.api.sse import SSE_RESPONSE_HEADERS
from app.core.security import create_scoped_token, decode_access_token
from app.db.session import SessionLocal, get_db
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.document import Document, DocumentSourceType
from app.models.document_group import DocumentGroup
from app.models.document_import import DocumentImport, DocumentImportAsset, DocumentImportStatus
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.storage_config import StorageConfig
from app.models.template_library import TemplateLibraryItem
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole
from app.models.user_group import UserGroup
from app.models.wechat_account import (
    WeChatAccount,
    WeChatBodyImageMaterial,
    WeChatCoverMaterial,
    WeChatDraft,
    WeChatDraftStatus,
    WeChatDraftSyncMode,
)
from app.schemas.document import (
    DocumentCreate,
    DocumentAiEditingStatus,
    DocumentDetail,
    DocumentHtmlPatch,
    DocumentImageLocalizationResult,
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
    DocumentVersionCopyCreate,
    DocumentVersionDetail,
    DocumentVersionSummary,
    VisibilityTargetsRead,
    WebArticleImportPreview,
    WebArticleImportPreviewRequest,
)
from app.schemas.wechat import (
    WeChatArticleMetadata,
    WeChatCoverUpload,
    WeChatDraftCreate,
    WeChatDraftRead,
    WeChatDraftTargetRead,
)
from app.schemas.layout_reference import LayoutCaptureSessionRead
from app.schemas.chat import ChatRevertRequest
from app.services import local_uploads, oss_client
from app.services.chat_sessions import ensure_default_chat_session
from app.services.chat_reask import ChatReaskError, activate_reask
from app.services.document_access import accessible_documents_query, can_access_document, can_access_document_group
from app.services.document_activity import touch_document, touch_group
from app.services.document_versions import (
    DocumentVersionStorageError,
    apply_single_splice,
    content_checksum,
    create_document_version,
    materialize_document_version,
)
from app.services.document_images import DocumentImageStorageError, store_document_image
from app.services.document_image_localization import (
    cleanup_document_localization,
    localize_document_html,
)
from app.services.external_fetch import PublicFetchError, fetch_public_image
from app.services.image_localization import ImageLocalizationError, ImageLocalizationResult
from app.services.chat_images import ChatImageError, delete_document_attachments
from app.services.document_shares import revoke_document_shares
from app.services.web_article_import import (
    WebArticleImportError,
    WebArticleImportExpiredError,
    cancel_web_article_import,
    complete_captured_web_article_import,
    complete_web_article_import,
    create_web_article_capture_session,
    create_web_article_import,
    get_web_article_import_preview_asset,
    web_article_import_preview_payload,
)
from app.services.browser_capture import WechatVerificationRequiredError
from app.services.wechat_official_account import BodyImageCacheEntry, CoverImage, WeChatApiError, WeChatOfficialAccountClient
from app.models.operation_log import OperationLogStatus
from app.services.operation_logs import (
    append_operation_log,
    get_operation_request_id,
    get_operation_request_metadata,
    set_request_audit_actor,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

MAX_IMPORT_FILE_SIZE = 30 * 1024 * 1024
MAX_REPLACEMENT_IMAGE_SIZE = 10 * 1024 * 1024
REPLACEABLE_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "avif", "bmp"}
SAFE_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif", "image/bmp"}
WECHAT_COVER_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp"}
IMPORT_SESSION_TTL = timedelta(hours=24)
IMPORT_UPLOAD_URL_EXPIRE_SECONDS = oss_client.DIRECT_UPLOAD_EXPIRE_SECONDS
OBJECT_VISIBILITY_RETRY_DELAYS = (0, 0.25, 0.5, 1, 2)
IMPORT_ASSET_TOKEN_PATTERN = re.compile(r"direct-import://asset/([0-9a-fA-F-]{36})")
SOURCE_DOWNLOAD_TOKEN_SCOPE = "document-source-download"
SOURCE_DOWNLOAD_TOKEN_MINUTES = 5
LOCAL_MANUAL_IMAGE_NAME_PATTERN = re.compile(r"[0-9a-f]{32}\.(?:jpg|png|gif|webp|avif|bmp)")
IMAGE_CONTENT_TYPES_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
    "bmp": "image/bmp",
}
SOURCE_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown",
}
ACTIVE_AGENT_RUN_STATUSES = {
    AgentRunStatus.PENDING,
    AgentRunStatus.RUNNING,
    AgentRunStatus.WAITING_FOR_INPUT,
    AgentRunStatus.CANCELLING,
}


def _is_document_being_edited_by_ai(db: Session, document_id: int) -> bool:
    return db.query(AgentRun.id).filter(
        AgentRun.document_id == document_id,
        AgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
    ).first() is not None


def _ensure_document_not_being_edited_by_ai(db: Session, document_id: int) -> None:
    if _is_document_being_edited_by_ai(db, document_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前推文正在由 AI 编辑，完成或停止后才能执行此操作",
        )


def _set_ai_editing_status(db: Session, document: Document) -> Document:
    document.is_ai_editing = _is_document_being_edited_by_ai(db, document.id)
    return document


def _set_ai_editing_statuses(db: Session, documents: list[Document]) -> list[Document]:
    document_ids = [document.id for document in documents]
    if not document_ids:
        return documents
    active_document_ids = {
        document_id
        for (document_id,) in db.query(AgentRun.document_id)
        .filter(
            AgentRun.document_id.in_(document_ids),
            AgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
        )
        .distinct()
        .all()
    }
    for document in documents:
        document.is_ai_editing = document.id in active_document_ids
    return documents


def _get_accessible_document(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if not document or not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return _set_ai_editing_status(db, document)


def _get_accessible_group(db: Session, group_id: int, user: User) -> DocumentGroup:
    group = db.get(DocumentGroup, group_id)
    if not group or not can_access_document_group(user, group):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    return group


def _ensure_document_visibility_manager(document: Document, user: User) -> None:
    if user.role != UserRole.ADMIN and document.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有推文创建人或管理员可以设置可见权限")


def _can_push_wechat_draft(current_user: User, account: WeChatAccount) -> bool:
    if current_user.role == UserRole.ADMIN or current_user.id in account.allowed_user_ids:
        return True
    return bool(set(account.allowed_group_ids) & {group.id for group in current_user.groups})


def _trusted_oss_image_hosts(db: Session) -> set[str]:
    """Trust only the concrete host produced by the configured storage signing client."""
    storage = _storage_if_configured(db)
    if storage is None:
        return set()
    try:
        signed_url = oss_client.sign_read_url(storage, "yibanpaiban/.wechat-host-check", expires=1)
    except Exception:  # Signing errors are reported by the normal upload/download path.
        return set()
    hostname = urlsplit(signed_url).hostname
    return {hostname.rstrip(".").lower()} if hostname else set()


def _wechat_draft_read(draft: WeChatDraft) -> WeChatDraftRead:
    return WeChatDraftRead(
        id=draft.id,
        account_id=draft.account_id,
        account_name=draft.account.name,
        status=draft.status.value,
        media_id=draft.media_id,
        sync_mode=draft.sync_mode.value,
        article_title=draft.article_title,
        error_code=draft.error_code,
        error_message=draft.error_message,
        created_by_name=(draft.created_by.display_name or draft.created_by.username) if draft.created_by else None,
        created_at=draft.created_at,
    )


def _unexpected_wechat_push_detail(request_id: str) -> str:
    reference = f"请求编号 {request_id}" if request_id else "请求时间"
    return f"推送服务发生内部错误，已记录失败；请重试，如仍失败请联系管理员并提供{reference}"


def _apply_wechat_metadata(document: Document, metadata: WeChatArticleMetadata) -> bool:
    fields = {
        "wechat_author": metadata.author,
        "wechat_digest": metadata.digest,
        "wechat_content_source_url": metadata.content_source_url,
        "wechat_cover_url": metadata.cover_url,
        "wechat_pic_crop_235_1": metadata.pic_crop_235_1,
        "wechat_pic_crop_1_1": metadata.pic_crop_1_1,
        "wechat_need_open_comment": metadata.need_open_comment,
        "wechat_only_fans_can_comment": metadata.only_fans_can_comment,
    }
    changed = False
    for name, value in fields.items():
        if getattr(document, name) != value:
            setattr(document, name, value)
            changed = True
    return changed


def _synchronize_document_title(document: Document, title: str) -> bool:
    """The article title is also the WeChat title; it must never diverge."""
    if document.title == title and document.wechat_title == title:
        return False
    document.title = title
    return True


def _storage_if_configured(db: Session) -> StorageConfig | None:
    storage = db.query(StorageConfig).first()
    if not storage or not storage.endpoint or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        return None
    return storage


def _configured_storage(db: Session) -> StorageConfig:
    storage = _storage_if_configured(db)
    if storage is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先联系管理员在「存储设置」中配置对象存储")
    return storage


def _storage_request_error(exc: Exception) -> HTTPException:
    if isinstance(exc, oss_client.OSSNotConfiguredError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, oss_client.ObjectStorageError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="对象存储操作失败，请检查配置与网络")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _utcnow()


def _safe_filename(filename: str, fallback: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    name = "".join(char for char in name if char.isprintable() and char not in {"\r", "\n"})
    return name[:512] or fallback


def _source_type_for_filename(filename: str) -> tuple[DocumentSourceType, str, str]:
    safe_name = _safe_filename(filename, "上传文件")
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if ext == "pdf":
        return DocumentSourceType.PDF, ext, SOURCE_CONTENT_TYPES[ext]
    if ext == "docx":
        return DocumentSourceType.WORD, ext, SOURCE_CONTENT_TYPES[ext]
    if ext == "md":
        return DocumentSourceType.MARKDOWN, ext, SOURCE_CONTENT_TYPES[ext]
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传 PDF、Word(.docx) 或 Markdown(.md) 文件")


def _direct_upload_target(storage: StorageConfig, object_key: str, content_type: str) -> dict[str, object]:
    """Normalize legacy string targets while all deployments roll to the structured contract."""
    try:
        target = oss_client.sign_direct_upload(storage, object_key, content_type)
    except Exception as exc:  # noqa: BLE001
        raise _storage_request_error(exc) from exc
    if isinstance(target, str):
        target = {
            "upload_url": target,
            "upload_method": "PUT",
            "upload_headers": {"Content-Type": content_type},
            "upload_fields": {},
            "file_field_name": "file",
        }
    return target


def _source_upload_target(storage: StorageConfig, import_session: DocumentImport) -> dict[str, object]:
    return {
        "object_key": import_session.source_object_key,
        "content_type": import_session.source_content_type,
        **_direct_upload_target(storage, import_session.source_object_key, import_session.source_content_type),
        "expires_in_seconds": IMPORT_UPLOAD_URL_EXPIRE_SECONDS,
    }


def _asset_upload_target(storage: StorageConfig, asset: DocumentImportAsset) -> dict[str, object]:
    return {
        "object_key": asset.object_key,
        "content_type": asset.content_type,
        **_direct_upload_target(storage, asset.object_key, asset.content_type),
        "expires_in_seconds": IMPORT_UPLOAD_URL_EXPIRE_SECONDS,
    }


def _import_uses_local_storage(import_session: DocumentImport) -> bool:
    return local_uploads.is_local_key(import_session.source_object_key)


def _import_upload_mode(import_session: DocumentImport) -> str:
    return "server" if _import_uses_local_storage(import_session) else "oss"


def _local_import_image_url(asset_id: str) -> str:
    return f"/api/documents/import-assets/{asset_id}"


def _local_document_image_payload(db: Session, document: Document, source: str) -> tuple[bytes, str, str] | None:
    """Read a locally stored article image for server-side WeChat material upload."""
    manual_prefix = "/api/documents/local-images/"
    import_prefix = "/api/documents/import-assets/"
    path = urlsplit(source).path if source.lower().startswith(("http://", "https://")) else source
    if path.startswith(manual_prefix):
        image_name = path.removeprefix(manual_prefix)
        if not LOCAL_MANUAL_IMAGE_NAME_PATTERN.fullmatch(image_name):
            return None
        try:
            data = local_uploads.local_path(f"local/images/{image_name}").read_bytes()
            image = local_uploads.inspect_image(data)
        except (OSError, local_uploads.LocalUploadError) as exc:
            raise WeChatApiError("本地图片不存在或已损坏，请重新上传") from exc
        return data, image.content_type, image_name
    if path.startswith(import_prefix):
        asset_id = path.removeprefix(import_prefix)
        asset = db.get(DocumentImportAsset, asset_id)
        if (
            asset is None
            or asset.import_session.status != DocumentImportStatus.COMPLETED
            or asset.import_session.document_id != document.id
            or not local_uploads.is_local_key(asset.object_key)
        ):
            return None
        try:
            data = local_uploads.local_path(asset.object_key).read_bytes()
            image = local_uploads.inspect_image(data)
        except (OSError, local_uploads.LocalUploadError) as exc:
            raise WeChatApiError("本地导入图片不存在或已损坏，请重新导入") from exc
        if image.content_type != asset.content_type:
            raise WeChatApiError("本地导入图片类型异常，请重新导入")
        return data, image.content_type, _safe_filename(asset.filename, f"image.{image.extension}")
    return None


def _localize_html_for_document_save(db: Session, document: Document, html: str) -> ImageLocalizationResult:
    try:
        return asyncio.run(localize_document_html(db, document, html))
    except ImageLocalizationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"正文图片不可发布：{exc}") from exc


def _local_source_url(document: Document, user: User) -> str:
    token = create_scoped_token(
        str(user.id),
        SOURCE_DOWNLOAD_TOKEN_SCOPE,
        {"document_id": document.id},
        expires_in_minutes=SOURCE_DOWNLOAD_TOKEN_MINUTES,
    )
    return f"/api/documents/{document.id}/source-file?token={quote(token, safe='')}"


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


def _expire_stale_imports(db: Session, storage: StorageConfig | None) -> None:
    """Best-effort cleanup for abandoned imports in either configured backend."""
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
            if local_uploads.is_local_key(object_key):
                local_uploads.delete(object_key)
            elif storage is not None:
                try:
                    oss_client.delete_object(storage, object_key)
                except Exception:  # Object may never have been uploaded or may have been removed by a lifecycle rule.
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
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{label}正在同步到对象存储，请稍候自动重试") from last_error


def _validate_local_source(import_session: DocumentImport) -> None:
    try:
        path = local_uploads.local_path(import_session.source_object_key)
        if not path.is_file() or path.stat().st_size != import_session.source_size:
            raise local_uploads.LocalUploadError("源文件未完成上传或大小不一致")
        local_uploads.validate_source(path, import_session.source_type)
    except local_uploads.LocalUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_local_asset(asset: DocumentImportAsset) -> None:
    try:
        path = local_uploads.local_path(asset.object_key)
        if not path.is_file() or path.stat().st_size != asset.size:
            raise local_uploads.LocalUploadError("解析图片未完成上传或大小不一致")
        local_uploads.validate_image(path, asset.content_type)
    except local_uploads.LocalUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_import_asset_metadata(filename: str, content_type: str, size: int) -> tuple[str, str]:
    safe_name = _safe_filename(filename, "image")
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    normalized_content_type = content_type.lower().split(";", 1)[0]
    if (
        extension not in REPLACEABLE_IMAGE_EXTENSIONS
        or normalized_content_type not in SAFE_IMAGE_CONTENT_TYPES
        or size > MAX_REPLACEMENT_IMAGE_SIZE
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持不超过 10MB 的 JPG、PNG、GIF、WebP、AVIF 或 BMP 图片",
        )
    return safe_name, normalized_content_type


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
    documents = (
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
    return _set_ai_editing_statuses(db, documents)


@router.get("/ai-editing-status", response_model=DocumentAiEditingStatus)
def get_ai_editing_status(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DocumentAiEditingStatus:
    active_document_ids = [
        document_id
        for (document_id,) in (
            accessible_documents_query(db.query(Document.id), current_user)
            .join(AgentRun, AgentRun.document_id == Document.id)
            .filter(AgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES))
            .distinct()
            .all()
        )
    ]
    return DocumentAiEditingStatus(active_document_ids=active_document_ids)


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
    normalized_content_type = payload.content_type.lower().split(";", 1)[0]
    accepted_content_types = {expected_content_type, "application/octet-stream"}
    if source_type == DocumentSourceType.MARKDOWN:
        accepted_content_types.add("text/plain")
    if normalized_content_type not in accepted_content_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件类型与扩展名不匹配")

    storage = _storage_if_configured(db)
    _expire_stale_imports(db, storage)
    import_id = str(uuid4())
    source_object_key = (
        f"yibanpaiban/direct-imports/{import_id}/source.{extension}"
        if storage is not None
        else local_uploads.import_source_key(import_id, extension)
    )
    import_session = DocumentImport(
        id=import_id,
        owner_id=current_user.id,
        source_type=source_type,
        source_filename=_safe_filename(payload.filename, "上传文件"),
        source_content_type=expected_content_type,
        source_size=payload.size,
        source_object_key=source_object_key,
        expires_at=_utcnow() + IMPORT_SESSION_TTL,
    )
    db.add(import_session)
    db.commit()
    db.refresh(import_session)
    return DocumentImportCreateResult(
        id=import_session.id,
        source_type=import_session.source_type,
        upload_mode=_import_upload_mode(import_session),
        source_upload=_source_upload_target(storage, import_session) if storage is not None else None,
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
            upload_mode=_import_upload_mode(import_session),
            source_upload=None,
            expires_at=import_session.expires_at,
            document_id=import_session.document_id,
        )

    storage = None if _import_uses_local_storage(import_session) else _configured_storage(db)
    assets = [
        DocumentImportAssetUpload(
            client_id=asset.client_id,
            asset_id=asset.id,
            upload=_asset_upload_target(storage, asset) if storage is not None else None,
        )
        for asset in import_session.assets
    ]
    return DocumentImportStatusRead(
        id=import_session.id,
        status=import_session.status.value,
        upload_mode=_import_upload_mode(import_session),
        source_upload=_source_upload_target(storage, import_session) if storage is not None else None,
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

    storage = None if _import_uses_local_storage(import_session) else _configured_storage(db)
    existing_by_client_id = {asset.client_id: asset for asset in import_session.assets}
    created_assets: list[DocumentImportAsset] = []
    for metadata in payload.assets:
        filename, content_type = _validate_import_asset_metadata(metadata.filename, metadata.content_type, metadata.size)
        extension = filename.rsplit(".", 1)[-1].lower()
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
            object_key=(
                f"yibanpaiban/direct-imports/{import_session.id}/assets/{asset_id}.{extension}"
                if storage is not None
                else local_uploads.import_asset_key(import_session.id, asset_id, extension)
            ),
        )
        db.add(asset)
        created_assets.append(asset)
    db.commit()
    return DocumentImportAssetsResult(
        assets=[
            DocumentImportAssetUpload(
                client_id=asset.client_id,
                asset_id=asset.id,
                upload=_asset_upload_target(storage, asset) if storage is not None else None,
            )
            for asset in created_assets
        ]
    )


@router.post(
    "/imports/{import_id}/source/upload",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def upload_local_import_source(
    import_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Receive a fallback source file only after its import envelope was authorized."""
    import_session = _get_import_session(db, import_id, current_user)
    _require_pending_import(import_session, db)
    if not _import_uses_local_storage(import_session):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该导入任务要求浏览器直传对象存储")
    try:
        await local_uploads.save_upload(
            file,
            import_session.source_object_key,
            MAX_IMPORT_FILE_SIZE,
            import_session.source_size,
            lambda path: local_uploads.validate_source(path, import_session.source_type),
        )
    except local_uploads.LocalUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post(
    "/imports/{import_id}/assets/{asset_id}/upload",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def upload_local_import_asset(
    import_id: str,
    asset_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Receive one previously declared, validated raster asset for a local import."""
    import_session = _get_import_session(db, import_id, current_user)
    _require_pending_import(import_session, db)
    if not _import_uses_local_storage(import_session):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该导入任务要求浏览器直传对象存储")
    asset = next((item for item in import_session.assets if item.id == asset_id), None)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="解析图片上传授权不存在")
    try:
        await local_uploads.save_upload(
            file,
            asset.object_key,
            MAX_REPLACEMENT_IMAGE_SIZE,
            asset.size,
            lambda path: local_uploads.validate_image(path, asset.content_type),
        )
    except local_uploads.LocalUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await file.close()


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
    storage = None if _import_uses_local_storage(import_session) else _configured_storage(db)
    if storage is None:
        _validate_local_source(import_session)
    else:
        _validate_uploaded_object(
            storage,
            import_session.source_object_key,
            import_session.source_content_type,
            import_session.source_size,
            "源文件",
        )

    assets_by_id = {asset.id: asset for asset in import_session.assets}
    referenced_asset_ids = set(IMPORT_ASSET_TOKEN_PATTERN.findall(payload.html))
    unknown_asset_ids = referenced_asset_ids - set(assets_by_id)
    if unknown_asset_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="解析图片清单与正文占位符不一致")

    html = payload.html
    for asset_id in referenced_asset_ids:
        asset = assets_by_id[asset_id]
        if storage is None:
            _validate_local_asset(asset)
            image_url = _local_import_image_url(asset.id)
        else:
            _validate_uploaded_object(storage, asset.object_key, asset.content_type, asset.size, "解析图片")
            image_url = oss_client.sign_read_url(storage, asset.object_key, oss_client.IMAGE_URL_EXPIRE_SECONDS)
        html = html.replace(
            f"direct-import://asset/{asset_id}",
            image_url,
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
    ensure_default_chat_session(db, document.id)
    create_document_version(
        db,
        document,
        current_user.id,
        DocumentVersionSource.INITIAL,
        "浏览器直传导入" if storage is not None else "服务器受限存储导入",
    )
    if group:
        touch_group(group, current_user.id)
    import_session.status = DocumentImportStatus.COMPLETED
    import_session.document_id = document.id
    db.commit()
    db.refresh(document)

    # Some Word parsers produce crop source assets that Mammoth later omits from HTML.
    # They are not part of the completed document, so remove them after its transaction commits.
    for asset_id, asset in assets_by_id.items():
        if asset_id in referenced_asset_ids:
            continue
        if local_uploads.is_local_key(asset.object_key):
            local_uploads.delete(asset.object_key)
        elif storage is not None:
            try:
                oss_client.delete_object(storage, asset.object_key)
            except Exception:
                pass
        db.delete(asset)
    if any(asset_id not in referenced_asset_ids for asset_id in assets_by_id):
        db.commit()
    return document


@router.post("/link-imports/preview", response_model=WebArticleImportPreview, status_code=status.HTTP_201_CREATED)
async def preview_web_article_import(
    payload: WebArticleImportPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        import_session, preview_token = await create_web_article_import(payload.url, current_user.id, db)
        db.commit()
        return web_article_import_preview_payload(import_session, preview_token)
    except WechatVerificationRequiredError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "wechat_verification_required",
                "message": str(exc),
                "url": exc.canonical_url,
            },
        ) from exc
    except WebArticleImportError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="文章链接解析失败，请稍后重试或更换公开链接") from exc


@router.post(
    "/link-imports/capture-sessions",
    response_model=LayoutCaptureSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def start_web_article_capture_session(
    payload: WebArticleImportPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        capture_session, token = create_web_article_capture_session(payload.url, current_user.id, db)
        db.commit()
        return {
            "id": capture_session.id,
            "token": token,
            "canonical_url": capture_session.canonical_url,
            "expires_at": capture_session.expires_at,
            "purpose": capture_session.purpose,
        }
    except WebArticleImportError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/link-imports/capture-sessions/{capture_id}/complete",
    response_model=WebArticleImportPreview,
)
async def complete_web_article_browser_capture(
    capture_id: str,
    request: Request,
    source_html: str = Form(..., min_length=1),
    title: str = Form(default="", max_length=256),
    manifest: str = Form(..., min_length=2),
    files: list[UploadFile] = File(default=[]),
    capture_token: str = Header(..., alias="X-Layout-Capture-Token", min_length=20, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    try:
        capture_manifest, captured_assets = await read_browser_capture_upload(manifest, files)
        import_session, preview_token = complete_captured_web_article_import(
            db,
            capture_id,
            capture_token,
            capture_manifest.url,
            source_html,
            title,
            captured_assets,
            capture_manifest.omitted_asset_count,
            capture_manifest.cover_asset_id,
        )
        actor = db.get(User, import_session.owner_id)
        if actor is not None:
            set_request_audit_actor(request, actor)
        db.commit()
        return web_article_import_preview_payload(import_session, preview_token)
    except BrowserCaptureUploadError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except WebArticleImportExpiredError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except WebArticleImportError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("浏览器采集链接导入失败", exc_info=exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="浏览器采集处理失败，请重新发起抓取") from exc
    finally:
        for file in files:
            await file.close()


@router.get("/link-imports/{import_id}/assets/{asset_id}")
def get_web_article_import_preview_asset_route(
    import_id: str,
    asset_id: str,
    preview_token: str = Query(min_length=20, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    try:
        asset = get_web_article_import_preview_asset(db, import_id, asset_id, preview_token)
    except WebArticleImportError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="链接导入图片已过期或不可用") from None
    return Response(
        content=asset.data,
        media_type=asset.content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.post("/link-imports/{import_id}/complete", response_model=DocumentDetail)
def complete_web_article_import_route(
    import_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    try:
        return complete_web_article_import(import_id, current_user, db)
    except WebArticleImportError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/link-imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel_web_article_import_route(
    import_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        cancel_web_article_import(import_id, current_user.id, db)
    except WebArticleImportError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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
    ensure_default_chat_session(db, document.id)
    create_document_version(db, document, current_user.id, DocumentVersionSource.INITIAL, "创建空白文档")
    if group:
        touch_group(group, current_user.id)
    db.commit()
    db.refresh(document)
    return document


@router.get("/crop-source")
async def get_crop_source_image(
    url: str = Query(min_length=1, max_length=8_192),
    _current_user: User = Depends(get_current_user),
) -> Response:
    """Read an external image through the application for the browser cropper.

    Image display does not require CORS, but exporting a crop requires readable
    bytes. Keep this authenticated endpoint behind the same bounded public-image
    fetcher used during article import so crop operations do not depend on the
    source server's browser CORS headers.
    """
    timeout = httpx.Timeout(10.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            data, image = await fetch_public_image(client, url)
    except PublicFetchError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="图片读取失败，请稍后重试") from exc
    return Response(
        content=data,
        media_type=image.content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if not document.has_source_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该文档没有可查看的原始文件")
    if local_uploads.is_local_key(document.source_object_key):
        return DocumentSourceAccess(
            filename=document.source_filename or "source",
            content_type=document.source_content_type or "application/octet-stream",
            size=document.source_size or 0,
            url=_local_source_url(document, current_user),
            expires_in_seconds=SOURCE_DOWNLOAD_TOKEN_MINUTES * 60,
        )
    storage = _configured_storage(db)
    return DocumentSourceAccess(
        filename=document.source_filename or "source",
        content_type=document.source_content_type or "application/octet-stream",
        size=document.source_size or 0,
        url=oss_client.sign_read_url(storage, document.source_object_key or ""),
        expires_in_seconds=oss_client.MANAGEMENT_URL_EXPIRE_SECONDS,
    )


@router.get("/{document_id}/source-file")
def download_local_document_source(document_id: int, token: str, db: Session = Depends(get_db)) -> FileResponse:
    """Serve a local source file only through a short-lived, document-scoped URL."""
    denied = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原文件不存在或链接已过期")
    try:
        claims = decode_access_token(token)
        if claims.get("scope") != SOURCE_DOWNLOAD_TOKEN_SCOPE or int(claims.get("document_id")) != document_id:
            raise denied
        user = db.get(User, int(claims["sub"]))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise denied
    if user is None or not user.is_active:
        raise denied
    document = db.get(Document, document_id)
    if not document or not can_access_document(user, document) or not local_uploads.is_local_key(document.source_object_key):
        raise denied
    try:
        path = local_uploads.local_path(document.source_object_key or "")
    except local_uploads.LocalUploadError:
        raise denied
    if not path.is_file():
        raise denied
    return FileResponse(
        path,
        media_type=document.source_content_type or "application/octet-stream",
        filename=document.source_filename or "source",
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get("/import-assets/{asset_id}")
def get_local_import_asset(asset_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Serve a completed local import image. The random asset ID is its capability URL."""
    asset = db.get(DocumentImportAsset, asset_id)
    if (
        asset is None
        or asset.import_session.status != DocumentImportStatus.COMPLETED
        or not local_uploads.is_local_key(asset.object_key)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    try:
        path = local_uploads.local_path(asset.object_key)
    except local_uploads.LocalUploadError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在") from None
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    return FileResponse(
        path,
        media_type=asset.content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.patch("/{document_id}", response_model=DocumentDetail)
def update_document(
    document_id: int,
    payload: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    changed = False
    version_changed = False
    metadata_title = None
    if payload.wechat_metadata is not None and "title" in payload.wechat_metadata.model_fields_set:
        metadata_title = payload.wechat_metadata.title
    if payload.title is not None and metadata_title is not None and payload.title != metadata_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="系统文章标题与微信标题必须一致",
        )
    next_title = payload.title if payload.title is not None else metadata_title
    if next_title is not None and _synchronize_document_title(document, next_title):
        changed = True
        version_changed = True
    if payload.wechat_metadata is not None:
        changed = _apply_wechat_metadata(document, payload.wechat_metadata) or changed
    if "group_id" in payload.model_fields_set and document.group_id != payload.group_id:
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
        _ensure_document_visibility_manager(document, current_user)
        visibility_mode = payload.visibility_mode or document.visibility_mode.value
        _apply_visibility(document, db, visibility_mode, payload.allowed_user_ids, payload.allowed_group_ids)
        changed = True
    if payload.current_html is not None:
        if document.current_html != payload.current_html:
            localization = _localize_html_for_document_save(db, document, payload.current_html)
            document.current_html = localization.html
            changed = True
            version_changed = True
    try:
        if changed:
            touch_document(document, current_user.id)
        if version_changed:
            create_document_version(db, document, current_user.id, DocumentVersionSource.MANUAL, "手动保存")
        db.commit()
    except Exception:
        if payload.current_html is not None and 'localization' in locals():
            cleanup_document_localization(db, localization)
        db.rollback()
        raise
    db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_document(
    document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    document = _get_accessible_document(db, document_id, current_user)
    try:
        delete_document_attachments(db, document.id)
        revoke_document_shares(db, document, current_user)
        db.delete(document)
        db.commit()
    except ChatImageError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


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
    message.superseded_at = datetime.now(timezone.utc)
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
        previous_user.superseded_at = datetime.now(timezone.utc)
    touch_document(document, current_user.id)
    db.commit()
    db.refresh(document)
    return document


@router.patch("/{document_id}/content", response_model=DocumentImageLocalizationResult)
def patch_document_content(
    document_id: int,
    payload: DocumentHtmlPatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImageLocalizationResult:
    """Persist a compact client-side splice without returning the full HTML again."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if content_checksum(document.current_html) != payload.base_checksum:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="文档已被其他修改更新，请刷新后再保存")
    try:
        next_html = apply_single_splice(
            document.current_html,
            payload.prefix_length,
            payload.suffix_length,
            payload.replacement,
        )
    except DocumentVersionStorageError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="保存补丁无效") from exc
    localization = _localize_html_for_document_save(db, document, next_html)
    try:
        document.current_html = localization.html
        touch_document(document, current_user.id)
        create_document_version(db, document, current_user.id, DocumentVersionSource.MANUAL, "手动保存")
        db.commit()
        return DocumentImageLocalizationResult(html=document.current_html, localized_count=localization.localized_count)
    except Exception:
        cleanup_document_localization(db, localization)
        db.rollback()
        raise


@router.get("/local-images/{image_name}")
def get_local_manual_image(image_name: str) -> FileResponse:
    """Expose only server-generated random image names, never a user-provided path."""
    if not LOCAL_MANUAL_IMAGE_NAME_PATTERN.fullmatch(image_name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    extension = image_name.rsplit(".", 1)[-1]
    try:
        path = local_uploads.local_path(f"local/images/{image_name}")
    except local_uploads.LocalUploadError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在") from None
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    return FileResponse(
        path,
        media_type=IMAGE_CONTENT_TYPES_BY_EXTENSION[extension],
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.post("/{document_id}/templates/{template_id}/materialize-images", response_model=DocumentImageLocalizationResult)
async def materialize_template_images(
    document_id: int,
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImageLocalizationResult:
    """Copy reusable component images into document storage before editor insertion."""
    document = _get_accessible_document(db, document_id, current_user)
    template = db.get(TemplateLibraryItem, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    try:
        result = await localize_document_html(db, document, template.html)
        return DocumentImageLocalizationResult(html=result.html, localized_count=result.localized_count)
    except ImageLocalizationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{document_id}/images/localize-external", response_model=DocumentImageLocalizationResult)
async def localize_document_images(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImageLocalizationResult:
    """Atomically copy every non-document image in the active article."""
    document = _get_accessible_document(db, document_id, current_user)
    _ensure_document_not_being_edited_by_ai(db, document.id)
    try:
        result = await localize_document_html(db, document, document.current_html)
    except ImageLocalizationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not result.localized_count:
        return DocumentImageLocalizationResult(html=document.current_html, localized_count=0)

    try:
        document.current_html = result.html
        touch_document(document, current_user.id)
        create_document_version(db, document, current_user.id, DocumentVersionSource.MANUAL, "转存外链图片")
        db.commit()
        db.refresh(document)
        return DocumentImageLocalizationResult(html=document.current_html, localized_count=result.localized_count)
    except Exception:
        cleanup_document_localization(db, result)
        db.rollback()
        raise


@router.post("/{document_id}/images", response_model=DocumentImageUpload)
async def upload_document_image(
    document_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentImageUpload:
    """Upload a validated image to object storage, or to private local fallback storage."""
    _get_accessible_document(db, document_id, current_user)
    try:
        data = await file.read(MAX_REPLACEMENT_IMAGE_SIZE + 1)
        if len(data) > MAX_REPLACEMENT_IMAGE_SIZE:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="图片不能超过 10MB")
        return DocumentImageUpload(url=store_document_image(db, data))
    except HTTPException:
        raise
    except DocumentImageStorageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"图片上传失败: {exc}") from exc
    finally:
        await file.close()


@router.post("/{document_id}/wechat-cover", response_model=WeChatCoverUpload)
async def upload_wechat_cover(
    document_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeChatCoverUpload:
    """Store a WeChat-compatible cover in the active backend for later server-side upload."""
    _get_accessible_document(db, document_id, current_user)
    try:
        data = await file.read(MAX_REPLACEMENT_IMAGE_SIZE + 1)
        if len(data) > MAX_REPLACEMENT_IMAGE_SIZE:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="封面不能超过 10MB")
        image = local_uploads.inspect_image(data)
        if image.content_type not in WECHAT_COVER_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="公众号封面仅支持 JPG、PNG、GIF 或 BMP 图片",
            )
        return WeChatCoverUpload(url=store_document_image(db, data, f"wechat-cover.{image.extension}"))
    except HTTPException:
        raise
    except local_uploads.LocalUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"封面上传失败: {exc}") from exc
    finally:
        await file.close()


@router.get("/{document_id}/wechat-drafts", response_model=list[WeChatDraftRead])
def list_wechat_drafts(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WeChatDraftRead]:
    document = _get_accessible_document(db, document_id, current_user)
    # History belongs to the document, not to the person who triggered a sync.
    # Every user with access to this document sees the same records.
    drafts = (
        db.query(WeChatDraft)
        .filter(WeChatDraft.document_id == document.id)
        .order_by(WeChatDraft.id.desc())
        .limit(100)
        .all()
    )
    return [_wechat_draft_read(draft) for draft in drafts]


@router.get("/{document_id}/wechat-drafts/targets", response_model=list[WeChatDraftTargetRead])
async def list_wechat_draft_targets(
    document_id: int,
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WeChatDraftTargetRead]:
    _get_accessible_document(db, document_id, current_user)
    account = db.get(WeChatAccount, account_id)
    if account is None or not account.is_active or not _can_push_wechat_draft(current_user, account):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有向该公众号推送草稿的权限")
    try:
        targets = await WeChatOfficialAccountClient().list_draft_targets(account)
    except WeChatApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [
        WeChatDraftTargetRead(
            media_id=target.media_id,
            title=target.title,
            update_time=target.update_time,
            article_count=target.article_count,
        )
        for target in targets
    ]


async def _push_wechat_draft(
    document_id: int,
    payload: WeChatDraftCreate,
    current_user: User,
    db: Session,
    progress_callback=None,
    request_id: str = "",
    client_ip: str = "",
    user_agent: str = "",
) -> WeChatDraftRead:
    async def report(stage: str, percent: int, detail: str) -> None:
        if progress_callback is not None:
            await progress_callback(stage, percent, detail)

    await report("validating", 24, "正在确认文章、目标公众号和推送权限…")
    document = _get_accessible_document(db, document_id, current_user)
    _ensure_document_not_being_edited_by_ai(db, document.id)
    account = db.get(WeChatAccount, payload.account_id)
    if account is None or not account.is_active or not _can_push_wechat_draft(current_user, account):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有向该公众号推送草稿的权限")
    target_media_id = payload.target_media_id
    if payload.sync_mode == "auto":
        latest_draft = (
            db.query(WeChatDraft)
            .filter(
                WeChatDraft.document_id == document.id,
                WeChatDraft.account_id == account.id,
                WeChatDraft.status == WeChatDraftStatus.SUCCEEDED,
                WeChatDraft.media_id.isnot(None),
            )
            .order_by(WeChatDraft.id.desc())
            .first()
        )
        if latest_draft is not None and latest_draft.media_id:
            sync_mode = WeChatDraftSyncMode.UPDATE
            target_media_id = latest_draft.media_id
            await report("validating", 27, "已找到上次成功同步的草稿，本次将直接覆盖其首篇图文…")
        else:
            sync_mode = WeChatDraftSyncMode.CREATE
            await report("validating", 27, "尚无成功同步记录，本次将创建新的微信草稿…")
    else:
        sync_mode = WeChatDraftSyncMode(payload.sync_mode)

    title = document.title.strip()
    if not title or len(title) > 32:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="系统文章标题需为 1 到 32 个字，才能同步至微信")
    metadata = WeChatArticleMetadata.model_validate({**document.wechat_metadata, "title": title})
    client = WeChatOfficialAccountClient()
    trusted_image_hosts = _trusted_oss_image_hosts(db)
    cover: CoverImage | None = None
    try:
        await report("validating", 29, "正在检查正文图片，必要时自动转存…")
        try:
            localization = await localize_document_html(db, document, document.current_html)
        except ImageLocalizationError as exc:
            raise WeChatApiError(f"同步前自动转存正文图片失败：{exc}") from exc
        if localization.localized_count:
            try:
                document.current_html = localization.html
                touch_document(document, current_user.id)
                create_document_version(db, document, current_user.id, DocumentVersionSource.MANUAL, "同步前自动转存图片")
                db.commit()
                db.refresh(document)
            except Exception:
                cleanup_document_localization(db, localization)
                db.rollback()
                raise
            await report("validating", 32, f"已自动转存 {localization.localized_count} 张正文图片，正在继续校验…")
        else:
            await report("validating", 32, "正文图片无需转存，正在继续校验…")
        await report("validating", 33, "正在校验微信字段、正文结构和图片地址…")
        WeChatOfficialAccountClient.validate_draft_input(metadata, document.current_html)
        if sync_mode == WeChatDraftSyncMode.UPDATE:
            await report("validating", 34, "正在确认要覆盖的微信草稿…")
            try:
                await client.validate_draft_target(account, target_media_id)
            except WeChatApiError as exc:
                if payload.sync_mode != "auto" or exc.code != 40007:
                    raise
                sync_mode = WeChatDraftSyncMode.CREATE
                target_media_id = ""
                await report("validating", 35, "上次同步的微信草稿已不存在，正在创建新的草稿…")
        await report("cover", 36, "正在下载并校验封面图片…")
        local_cover = _local_document_image_payload(db, document, metadata.cover_url)
        if local_cover is None:
            cover = await client.download_cover(metadata.cover_url, trusted_image_hosts=trusted_image_hosts)
        else:
            content, content_type, filename = local_cover
            if content_type not in WECHAT_COVER_CONTENT_TYPES:
                raise WeChatApiError("公众号封面仅支持 JPG、PNG、GIF 或 BMP 图片")
            cover = CoverImage(content=content, content_type=content_type, filename=filename)
        cached_material = (
            db.query(WeChatCoverMaterial)
            .filter(
                WeChatCoverMaterial.account_id == account.id,
                WeChatCoverMaterial.content_sha256 == cover.content_sha256,
            )
            .first()
        )
        await report(
            "cover",
            39,
            "封面校验完成，已命中永久素材缓存…" if cached_material else "封面校验完成，稍后上传永久素材…",
        )
        body_image_cache = {
            item.source_url_sha256: BodyImageCacheEntry(
                source_url_sha256=item.source_url_sha256,
                content_sha256=item.content_sha256,
                content_type=item.content_type,
                wechat_url=item.wechat_url,
                upload_mode=item.upload_mode,
            )
            for item in db.query(WeChatBodyImageMaterial)
            .filter(WeChatBodyImageMaterial.account_id == account.id)
            .all()
        }
        push_kwargs = {
            "html": document.current_html,
            "metadata": metadata,
            "cover": cover,
            "cached_cover_media_id": cached_material.media_id if cached_material else None,
            "cached_body_images": body_image_cache,
            "trusted_image_hosts": trusted_image_hosts,
            "local_image_loader": lambda source: _local_document_image_payload(db, document, source),
            "progress_callback": progress_callback,
        }
        if sync_mode == WeChatDraftSyncMode.UPDATE:
            result = await client.update_draft(
                account,
                target_media_id=target_media_id,
                fallback_to_create_on_invalid_target=payload.sync_mode == "auto",
                **push_kwargs,
            )
            if result.created_new_draft:
                sync_mode = WeChatDraftSyncMode.CREATE
                target_media_id = ""
        else:
            result = await client.create_draft(account, **push_kwargs)
    except WeChatApiError as exc:
        if cover is not None:
            cover.close()
        draft = WeChatDraft(
            document_id=document.id,
            account_id=account.id,
            created_by_id=current_user.id,
            status=WeChatDraftStatus.FAILED,
            sync_mode=sync_mode,
            article_title=metadata.title,
            error_code=exc.code,
            error_message=str(exc)[:1024],
        )
        db.add(draft)
        append_operation_log(
            db,
            actor=current_user,
            action="wechat.draft.push",
            resource_type="wechat_draft",
            resource_id=str(document.id),
            resource_name=document.title,
            document_id=document.id,
            status=OperationLogStatus.FAILED,
            summary="公众号草稿推送失败",
            error_summary=f"公众号接口错误{f'（{exc.code}）' if exc.code is not None else ''}",
            details={"account_id": account.id, "sync_mode": sync_mode.value},
            request_id=request_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        db.commit()
        db.refresh(draft)
        http_status = status.HTTP_502_BAD_GATEWAY if exc.code is not None else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=http_status, detail=str(exc)) from exc
    except HTTPException:
        if cover is not None:
            cover.close()
        raise
    except Exception as exc:  # noqa: BLE001 - the stream must not hide application failures.
        if cover is not None:
            cover.close()
        detail = _unexpected_wechat_push_detail(request_id)
        logger.exception(
            "wechat_draft_push_unexpected_failure request_id=%s document_id=%s account_id=%s",
            request_id or "-",
            document.id,
            account.id,
        )
        try:
            db.rollback()
            draft = WeChatDraft(
                document_id=document.id,
                account_id=account.id,
                created_by_id=current_user.id,
                status=WeChatDraftStatus.FAILED,
                sync_mode=sync_mode,
                article_title=metadata.title,
                error_message=detail[:1024],
            )
            db.add(draft)
            append_operation_log(
                db,
                actor=current_user,
                action="wechat.draft.push",
                resource_type="wechat_draft",
                resource_id=str(document.id),
                resource_name=document.title,
                document_id=document.id,
                status=OperationLogStatus.FAILED,
                summary="公众号草稿推送失败",
                error_summary="推送服务内部错误",
                details={"account_id": account.id, "sync_mode": sync_mode.value},
                request_id=request_id,
                client_ip=client_ip,
                user_agent=user_agent,
            )
            db.commit()
        except Exception:  # noqa: BLE001 - a database outage must not mask the original failure.
            db.rollback()
            logger.exception(
                "wechat_draft_failure_record_unavailable request_id=%s document_id=%s account_id=%s",
                request_id or "-",
                document.id,
                account.id,
            )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from exc
    except BaseException:
        if cover is not None:
            cover.close()
        raise
    else:
        # The real client also closes its cover stream; route-level cleanup
        # keeps mocked clients and future alternate implementations leak-free.
        assert cover is not None
        cover.close()

    if result.cover_media_was_uploaded and cached_material is None:
        db.add(
            WeChatCoverMaterial(
                account_id=account.id,
                content_sha256=cover.content_sha256,
                media_id=result.cover_media_id,
            )
        )
    for entry in result.body_image_cache_entries:
        cached_image = (
            db.query(WeChatBodyImageMaterial)
            .filter(
                WeChatBodyImageMaterial.account_id == account.id,
                WeChatBodyImageMaterial.source_url_sha256 == entry.source_url_sha256,
            )
            .first()
        )
        if cached_image is None:
            db.add(
                WeChatBodyImageMaterial(
                    account_id=account.id,
                    source_url_sha256=entry.source_url_sha256,
                    content_sha256=entry.content_sha256,
                    content_type=entry.content_type,
                    wechat_url=entry.wechat_url,
                    upload_mode=entry.upload_mode,
                )
            )
        else:
            cached_image.content_sha256 = entry.content_sha256
            cached_image.content_type = entry.content_type
            cached_image.wechat_url = entry.wechat_url
            cached_image.upload_mode = entry.upload_mode
    draft = WeChatDraft(
        document_id=document.id,
        account_id=account.id,
        created_by_id=current_user.id,
        status=WeChatDraftStatus.SUCCEEDED,
        sync_mode=sync_mode,
        media_id=result.media_id,
        article_title=metadata.title,
    )
    db.add(draft)
    append_operation_log(
        db,
        actor=current_user,
        action="wechat.draft.push",
        resource_type="wechat_draft",
        resource_id=str(document.id),
        resource_name=document.title,
        document_id=document.id,
        status=OperationLogStatus.SUCCEEDED,
        summary="公众号草稿已更新" if sync_mode == WeChatDraftSyncMode.UPDATE else "公众号草稿已创建",
        details={"account_id": account.id, "sync_mode": sync_mode.value},
        request_id=request_id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(draft)
    await report("history", 98, "推送记录已保存，正在返回草稿结果…")
    return _wechat_draft_read(draft)


async def _push_wechat_draft_in_task_session(
    document_id: int,
    payload: WeChatDraftCreate,
    current_user_id: int,
    progress_callback=None,
    request_id: str = "",
    client_ip: str = "",
    user_agent: str = "",
) -> WeChatDraftRead:
    """Run an SSE push using data attached to a task-owned database session."""
    task_db = SessionLocal()
    try:
        current_user = task_db.get(User, current_user_id)
        if current_user is None or not current_user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
        return await _push_wechat_draft(
            document_id,
            payload,
            current_user,
            task_db,
            progress_callback,
            request_id,
            client_ip,
            user_agent,
        )
    finally:
        task_db.close()


@router.post("/{document_id}/wechat-drafts", response_model=WeChatDraftRead)
async def create_wechat_draft(
    document_id: int,
    payload: WeChatDraftCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeChatDraftRead:
    metadata = get_operation_request_metadata()
    return await _push_wechat_draft(
        document_id,
        payload,
        current_user,
        db,
        request_id=get_operation_request_id(),
        client_ip=metadata.client_ip,
        user_agent=metadata.user_agent,
    )


def _wechat_draft_sse_event(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/{document_id}/wechat-drafts/stream")
async def stream_wechat_draft(
    document_id: int,
    payload: WeChatDraftCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    request_id = get_operation_request_id()
    metadata = get_operation_request_metadata()
    current_user_id = current_user.id

    async def event_stream():
        progress_events: asyncio.Queue[dict[str, object]] = asyncio.Queue()

        async def report(stage: str, percent: int, detail: str) -> None:
            await progress_events.put({"stage": stage, "percent": percent, "detail": detail})

        task = asyncio.create_task(
            _push_wechat_draft_in_task_session(
                document_id,
                payload,
                current_user_id,
                report,
                request_id,
                metadata.client_ip,
                metadata.user_agent,
            )
        )
        try:
            while not task.done() or not progress_events.empty():
                try:
                    event = await asyncio.wait_for(progress_events.get(), timeout=0.25)
                except TimeoutError:
                    continue
                yield _wechat_draft_sse_event("progress", event)

            try:
                draft = task.result()
            except HTTPException as exc:
                yield _wechat_draft_sse_event("error", {"status": exc.status_code, "detail": exc.detail})
            except Exception:  # noqa: BLE001
                detail = _unexpected_wechat_push_detail(request_id)
                logger.exception(
                    "wechat_draft_stream_unexpected_failure request_id=%s document_id=%s",
                    request_id or "-",
                    document_id,
                )
                yield _wechat_draft_sse_event("error", {"status": 500, "detail": detail})
            else:
                yield _wechat_draft_sse_event("result", draft.model_dump(mode="json"))
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )


@router.post("/{document_id}/revert-to-message", response_model=DocumentDetail)
def revert_to_message(
    document_id: int,
    payload: ChatRevertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """Legacy two-request re-ask entry point for older web clients."""
    document = db.query(Document).filter(Document.id == document_id).with_for_update().first()
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
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
    session = db.get(ChatSession, target_message.session_id)
    if session is None or session.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史消息所属对话不存在")
    try:
        activate_reask(db, document=document, session=session, source_message_id=target_message.id)
    except ChatReaskError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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
) -> DocumentVersionDetail:
    _get_accessible_document(db, document_id, current_user)
    version = (
        db.query(DocumentVersion)
        .options(selectinload(DocumentVersion.created_by))
        .filter(DocumentVersion.id == version_id, DocumentVersion.document_id == document_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    try:
        html = materialize_document_version(db, version)
    except DocumentVersionStorageError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="版本内容无法读取") from exc
    return DocumentVersionDetail(
        id=version.id,
        version_number=version.version_number,
        title=version.title,
        source=version.source,
        label=version.label,
        created_by=version.created_by,
        created_at=version.created_at,
        html=html,
    )


@router.post("/{document_id}/versions/{version_id}/restore", response_model=DocumentDetail)
def restore_document_version(
    document_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.id == version_id, DocumentVersion.document_id == document_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    try:
        version_html = materialize_document_version(db, version)
    except DocumentVersionStorageError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="版本内容无法读取") from exc
    document.title = version.title
    document.current_html = version_html
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


@router.post("/{document_id}/versions/{version_id}/copy", response_model=DocumentDetail)
def copy_document_version(
    document_id: int,
    version_id: int,
    payload: DocumentVersionCopyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """Create an independent article from one immutable historical snapshot."""
    _get_accessible_document(db, document_id, current_user)
    version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.id == version_id, DocumentVersion.document_id == document_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    try:
        version_html = materialize_document_version(db, version)
    except DocumentVersionStorageError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="版本内容无法读取") from exc

    group = _get_accessible_group(db, payload.group_id, current_user) if payload.group_id is not None else None
    document = Document(
        owner_id=current_user.id,
        group_id=group.id if group else None,
        created_by_id=current_user.id,
        last_modified_by_id=current_user.id,
        title=payload.title,
        current_html=version_html,
        source_type=DocumentSourceType.BLANK,
        visibility_mode=VisibilityMode(payload.visibility_mode),
    )
    _apply_visibility(document, db, payload.visibility_mode, payload.allowed_user_ids, payload.allowed_group_ids)
    db.add(document)
    db.flush()
    ensure_default_chat_session(db, document.id)
    create_document_version(
        db,
        document,
        current_user.id,
        DocumentVersionSource.INITIAL,
        f"从 v{version.version_number} 复制创建",
    )
    if group:
        touch_group(group, current_user.id)
    db.commit()
    db.refresh(document)
    return document


