import uuid
from pathlib import Path
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.core.security import create_scoped_token, decode_access_token
from app.db.session import get_db
from app.models.storage_config import StorageConfig
from app.models.document import Document
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.user import User, UserRole
from app.schemas.storage import (
    StorageConfigRead,
    StorageConfigUpdate,
    StorageDirectUploadCheck,
    StorageDirectUploadCheckVerify,
    StorageImageRepairResult,
    StorageObjectListResult,
    StorageObjectRead,
    StorageObjectUrlResult,
    StorageTestResult,
)
from app.services import local_uploads, oss_client
from app.services.document_activity import touch_document, touch_group

router = APIRouter(prefix="/api/storage", tags=["storage"], dependencies=[Depends(require_admin)])
public_router = APIRouter(prefix="/api/storage", tags=["storage"])

MAX_MANAGED_UPLOAD_SIZE = 50 * 1024 * 1024
DIRECT_UPLOAD_CHECK_PAYLOAD = b"yibanpaiban-direct-upload-check"
DIRECT_UPLOAD_CHECK_PREFIX = "yibanpaiban/_direct_upload_check/"
LOCAL_MANAGED_OBJECT_SCOPE = "local-managed-object"


def _get_or_create_config(db: Session) -> StorageConfig:
    config = db.query(StorageConfig).first()
    if not config:
        config = StorageConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def _to_read(config: StorageConfig) -> StorageConfigRead:
    secret_plain = decrypt_secret(config.access_key_secret_encrypted) if config.access_key_secret_encrypted else ""
    return StorageConfigRead(
        configured=bool(config.endpoint and config.access_key_id and config.access_key_secret_encrypted and config.bucket),
        provider=config.provider or oss_client.ALIYUN_OSS,
        endpoint=config.endpoint,
        bucket=config.bucket,
        access_key_id=config.access_key_id,
        access_key_secret_masked=mask_secret(secret_plain),
        region_or_zone=config.region_or_zone,
        upload_endpoint=config.upload_endpoint,
        custom_domain=config.custom_domain,
    )


def _configured_storage(db: Session) -> StorageConfig:
    config = _get_or_create_config(db)
    if not config.endpoint or not config.access_key_id or not config.access_key_secret_encrypted or not config.bucket:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先在存储设置中完成对象存储配置")
    return config


def _storage_if_configured(db: Session) -> StorageConfig | None:
    config = _get_or_create_config(db)
    if not config.endpoint or not config.access_key_id or not config.access_key_secret_encrypted or not config.bucket:
        return None
    return config


def _local_object_url(object_key: str, user: User) -> str:
    token = create_scoped_token(
        str(user.id),
        LOCAL_MANAGED_OBJECT_SCOPE,
        {"object_key": object_key},
        expires_in_minutes=max(1, oss_client.MANAGEMENT_URL_EXPIRE_SECONDS // 60),
    )
    return f"/api/storage/local-objects/{quote(object_key, safe='/')}?token={quote(token, safe='')}"


def _local_object_media_type(path: Path) -> str:
    try:
        return local_uploads.inspect_image(path.read_bytes()).content_type
    except (OSError, local_uploads.LocalUploadError):
        pass
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            if b"%PDF-" in path.read_bytes()[:1024]:
                return "application/pdf"
        except OSError:
            pass
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/plain",
        ".txt": "text/plain",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".ogg": "video/ogg",
    }.get(suffix, "application/octet-stream")


def _storage_error(exc: Exception) -> HTTPException:
    if isinstance(exc, oss_client.OSSNotConfiguredError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, oss_client.ObjectStorageError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="对象存储操作失败，请检查配置与网络")


def _direct_upload_target(config: StorageConfig, object_key: str, content_type: str) -> dict:
    """Accept the legacy string return during rolling upgrades and old test mocks."""
    target = oss_client.sign_direct_upload(config, object_key, content_type)
    if isinstance(target, str):
        return {
            "upload_url": target,
            "upload_method": "PUT",
            "upload_headers": {"Content-Type": content_type},
            "upload_fields": {},
            "file_field_name": "file",
        }
    return target


@router.get("", response_model=StorageConfigRead)
def get_storage(db: Session = Depends(get_db)) -> StorageConfigRead:
    return _to_read(_get_or_create_config(db))


@router.put("", response_model=StorageConfigRead)
def update_storage(payload: StorageConfigUpdate, db: Session = Depends(get_db)) -> StorageConfigRead:
    config = _get_or_create_config(db)
    config.provider = payload.provider
    config.endpoint = payload.endpoint.strip()
    config.bucket = payload.bucket.strip()
    config.access_key_id = payload.access_key_id.strip()
    config.region_or_zone = payload.region_or_zone.strip()
    config.upload_endpoint = payload.upload_endpoint.strip()
    config.custom_domain = payload.custom_domain.strip()
    if payload.access_key_secret:
        config.access_key_secret_encrypted = encrypt_secret(payload.access_key_secret)
    db.commit()
    db.refresh(config)
    return _to_read(config)


@router.get("/objects", response_model=StorageObjectListResult)
def list_storage_objects(
    prefix: str = "",
    marker: str = "",
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
) -> StorageObjectListResult:
    try:
        storage = _storage_if_configured(db)
        if storage is None:
            return StorageObjectListResult(**local_uploads.list_managed_objects(prefix, marker, limit))
        return StorageObjectListResult(**oss_client.list_objects(storage, prefix, marker, limit))
    except Exception as exc:  # noqa: BLE001
        raise _storage_error(exc) from exc


@router.post("/objects/upload", response_model=StorageObjectRead)
async def upload_storage_object(
    file: UploadFile = File(...),
    prefix: str = "",
    db: Session = Depends(get_db),
) -> StorageObjectRead:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择要上传的文件")
    data = await file.read(MAX_MANAGED_UPLOAD_SIZE + 1)
    if len(data) > MAX_MANAGED_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="单个文件不能超过 50 MB")
    try:
        storage = _storage_if_configured(db)
        if storage is None:
            return StorageObjectRead(**local_uploads.save_managed_object(data, file.filename, prefix))
        return StorageObjectRead(
            **oss_client.upload_managed_file(storage, data, file.filename, file.content_type, prefix)
        )
    except Exception as exc:  # noqa: BLE001
        raise _storage_error(exc) from exc
    finally:
        await file.close()


@router.get("/objects/{object_key:path}/preview", response_model=StorageObjectUrlResult)
def preview_storage_object(
    object_key: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StorageObjectUrlResult:
    try:
        storage = _storage_if_configured(db)
        if storage is None:
            path = local_uploads.managed_object_path(object_key)
            if not path.is_file():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
            return StorageObjectUrlResult(
                url=_local_object_url(object_key, current_user),
                expires_in_seconds=oss_client.MANAGEMENT_URL_EXPIRE_SECONDS,
            )
        return StorageObjectUrlResult(
            url=oss_client.management_url(storage, object_key),
            expires_in_seconds=oss_client.MANAGEMENT_URL_EXPIRE_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        raise _storage_error(exc) from exc


@router.delete("/objects/{object_key:path}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_storage_object(object_key: str, db: Session = Depends(get_db)) -> None:
    try:
        storage = _storage_if_configured(db)
        if storage is None:
            path = local_uploads.managed_object_path(object_key)
            if path.exists() and not path.is_file():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能删除文件")
            path.unlink(missing_ok=True)
            return
        oss_client.delete_object(storage, object_key)
    except Exception as exc:  # noqa: BLE001
        raise _storage_error(exc) from exc


@router.post("/test", response_model=StorageTestResult)
def test_storage(db: Session = Depends(get_db)) -> StorageTestResult:
    config = _storage_if_configured(db)
    if config is None:
        try:
            local_uploads.local_path(local_uploads.MANAGED_OBJECT_PREFIX.rstrip("/")).mkdir(parents=True, exist_ok=True)
        except (OSError, local_uploads.LocalUploadError) as exc:
            return StorageTestResult(success=False, message=f"本地存储不可用：{exc}")
        return StorageTestResult(success=True, message="本地存储可用：文件将保存在服务器磁盘")
    success, message = oss_client.test_connection(config)
    return StorageTestResult(success=success, message=message)


@router.post("/direct-upload-check", response_model=StorageDirectUploadCheck)
def create_direct_upload_check(db: Session = Depends(get_db)) -> StorageDirectUploadCheck:
    try:
        config = _configured_storage(db)
        object_key = f"{DIRECT_UPLOAD_CHECK_PREFIX}{uuid.uuid4().hex}.txt"
        target = _direct_upload_target(config, object_key, "text/plain")
        return StorageDirectUploadCheck(
            object_key=object_key,
            content_type="text/plain",
            **target,
            expected_size=len(DIRECT_UPLOAD_CHECK_PAYLOAD),
            expires_in_seconds=oss_client.DIRECT_UPLOAD_EXPIRE_SECONDS,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _storage_error(exc) from exc


@router.post("/direct-upload-check/verify", response_model=StorageTestResult)
def verify_direct_upload_check(
    payload: StorageDirectUploadCheckVerify, db: Session = Depends(get_db)
) -> StorageTestResult:
    if not payload.object_key.startswith(DIRECT_UPLOAD_CHECK_PREFIX) or not payload.object_key.endswith(".txt"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的直传测试对象")
    config = _configured_storage(db)
    try:
        metadata = oss_client.inspect_object(config, payload.object_key)
        if metadata["size"] != len(DIRECT_UPLOAD_CHECK_PAYLOAD) or metadata["content_type"] != "text/plain":
            return StorageTestResult(success=False, message="直传对象校验失败，请检查对象存储 CORS 与上传请求头")
        oss_client.delete_object(config, payload.object_key)
        return StorageTestResult(success=True, message="浏览器直传对象存储成功，CORS 配置可用")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (oss_client.OSSNotConfiguredError, oss_client.ObjectStorageError, ValueError)):
            return StorageTestResult(success=False, message=f"无法校验浏览器直传：{exc}")
        return StorageTestResult(success=False, message="无法校验浏览器直传，请检查对象存储配置与网络")


@router.post("/repair-image-access", response_model=StorageImageRepairResult)
def repair_image_access(
    current_user=Depends(require_admin), db: Session = Depends(get_db)
) -> StorageImageRepairResult:
    config = _storage_if_configured(db)
    if config is None:
        return StorageImageRepairResult(repaired_count=0, message="当前使用本地存储，无需修复对象存储图片链接")
    try:
        snapshots = db.query(Document.id, Document.current_html).order_by(Document.id).all()
        active_statuses = [AgentRunStatus.PENDING, AgentRunStatus.RUNNING,
                           AgentRunStatus.WAITING_FOR_INPUT, AgentRunStatus.CANCELLING]
        repaired_count = skipped_count = 0
        for document_id, source_html in snapshots:
            active_query = db.query(AgentRun.id).filter(
                AgentRun.document_id == document_id, AgentRun.status.in_(active_statuses),
            )
            if active_query.first() is not None:
                skipped_count += 1
                continue
            refreshed_htmls, count = oss_client.refresh_document_image_urls(config, [source_html])
            refreshed_html = refreshed_htmls[0]
            document = (db.query(Document).filter(Document.id == document_id)
                        .populate_existing().with_for_update().first())
            if (document is None or document.current_html != source_html
                    or active_query.with_for_update().first() is not None):
                skipped_count += 1
                continue
            if document.current_html != refreshed_html:
                document.current_html = refreshed_html
                repaired_count += count
                touch_document(document, current_user.id)
                if document.group:
                    touch_group(document.group, current_user.id)
        db.commit()
        return StorageImageRepairResult(
            repaired_count=repaired_count,
            message=(f"已更新 {repaired_count} 张已导入图片的访问链接"
                     + (f"；已跳过 {skipped_count} 篇正在编辑或已变化的文档" if skipped_count else "")),
        )
    except (oss_client.OSSNotConfiguredError, oss_client.ObjectStorageError, ValueError) as e:
        db.rollback()
        return StorageImageRepairResult(repaired_count=0, message=str(e))
    except Exception:  # noqa: BLE001 将未知上传/网络错误转为可见结果
        db.rollback()
        return StorageImageRepairResult(repaired_count=0, message="修复失败，请检查对象存储配置与网络")


@public_router.get("/local-objects/{object_key:path}")
def get_local_storage_object(object_key: str, token: str, db: Session = Depends(get_db)) -> FileResponse:
    """Serve a short-lived, administrator-scoped local management file URL."""
    denied = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    try:
        claims = decode_access_token(token)
        if claims.get("scope") != LOCAL_MANAGED_OBJECT_SCOPE or claims.get("object_key") != object_key:
            raise denied
        user = db.get(User, int(claims["sub"]))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise denied
    if user is None or not user.is_active or user.role != UserRole.ADMIN:
        raise denied
    try:
        path = local_uploads.managed_object_path(object_key)
    except local_uploads.LocalUploadError:
        raise denied from None
    if not path.is_file():
        raise denied
    return FileResponse(
        path,
        media_type=_local_object_media_type(path),
        filename=path.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )
