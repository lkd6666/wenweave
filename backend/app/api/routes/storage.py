import uuid

import oss2

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.db.session import get_db
from app.models.storage_config import StorageConfig
from app.models.document import Document
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
from app.services import oss_client
from app.services.document_activity import touch_document, touch_group

router = APIRouter(prefix="/api/storage", tags=["storage"], dependencies=[Depends(require_admin)])

MAX_MANAGED_UPLOAD_SIZE = 50 * 1024 * 1024
DIRECT_UPLOAD_CHECK_PAYLOAD = b"yibanpaiban-direct-upload-check"
DIRECT_UPLOAD_CHECK_PREFIX = "yibanpaiban/_direct_upload_check/"


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
        configured=bool(config.access_key_id and config.access_key_secret_encrypted and config.bucket),
        endpoint=config.endpoint,
        bucket=config.bucket,
        access_key_id=config.access_key_id,
        access_key_secret_masked=mask_secret(secret_plain),
        custom_domain=config.custom_domain,
    )


def _configured_storage(db: Session) -> StorageConfig:
    config = _get_or_create_config(db)
    if not config.access_key_id or not config.access_key_secret_encrypted or not config.bucket:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先在存储设置中完成 OSS 配置")
    return config


def _oss_error(exc: Exception) -> HTTPException:
    if isinstance(exc, oss_client.OSSNotConfiguredError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, oss2.exceptions.OssError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OSS 错误: {exc.code} {exc.message}")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OSS 操作失败: {exc}")


@router.get("", response_model=StorageConfigRead)
def get_storage(db: Session = Depends(get_db)) -> StorageConfigRead:
    return _to_read(_get_or_create_config(db))


@router.put("", response_model=StorageConfigRead)
def update_storage(payload: StorageConfigUpdate, db: Session = Depends(get_db)) -> StorageConfigRead:
    config = _get_or_create_config(db)
    config.endpoint = payload.endpoint.strip()
    config.bucket = payload.bucket.strip()
    config.access_key_id = payload.access_key_id.strip()
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
        return StorageObjectListResult(**oss_client.list_objects(_configured_storage(db), prefix, marker, limit))
    except Exception as exc:  # noqa: BLE001
        raise _oss_error(exc) from exc


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
        return StorageObjectRead(
            **oss_client.upload_managed_file(_configured_storage(db), data, file.filename, file.content_type, prefix)
        )
    except Exception as exc:  # noqa: BLE001
        raise _oss_error(exc) from exc
    finally:
        await file.close()


@router.get("/objects/{object_key:path}/preview", response_model=StorageObjectUrlResult)
def preview_storage_object(object_key: str, db: Session = Depends(get_db)) -> StorageObjectUrlResult:
    try:
        return StorageObjectUrlResult(
            url=oss_client.management_url(_configured_storage(db), object_key),
            expires_in_seconds=oss_client.MANAGEMENT_URL_EXPIRE_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        raise _oss_error(exc) from exc


@router.delete("/objects/{object_key:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_storage_object(object_key: str, db: Session = Depends(get_db)) -> None:
    try:
        oss_client.delete_object(_configured_storage(db), object_key)
    except Exception as exc:  # noqa: BLE001
        raise _oss_error(exc) from exc


@router.post("/test", response_model=StorageTestResult)
def test_storage(db: Session = Depends(get_db)) -> StorageTestResult:
    config = _get_or_create_config(db)
    if not config.access_key_id or not config.access_key_secret_encrypted or not config.bucket:
        return StorageTestResult(success=False, message="请先完整填写 Endpoint / Bucket / AccessKey 后再测试")
    success, message = oss_client.test_connection(config)
    return StorageTestResult(success=success, message=message)


@router.post("/direct-upload-check", response_model=StorageDirectUploadCheck)
def create_direct_upload_check(db: Session = Depends(get_db)) -> StorageDirectUploadCheck:
    config = _configured_storage(db)
    object_key = f"{DIRECT_UPLOAD_CHECK_PREFIX}{uuid.uuid4().hex}.txt"
    return StorageDirectUploadCheck(
        object_key=object_key,
        upload_url=oss_client.sign_direct_upload(config, object_key, "text/plain"),
        content_type="text/plain",
        expected_size=len(DIRECT_UPLOAD_CHECK_PAYLOAD),
        expires_in_seconds=oss_client.DIRECT_UPLOAD_EXPIRE_SECONDS,
    )


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
            return StorageTestResult(success=False, message="直传对象校验失败，请检查 OSS CORS 与上传请求头")
        oss_client.delete_object(config, payload.object_key)
        return StorageTestResult(success=True, message="浏览器直传 OSS 成功，CORS 配置可用")
    except Exception as exc:  # noqa: BLE001
        return StorageTestResult(success=False, message=f"无法校验浏览器直传：{exc}")


@router.post("/repair-image-access", response_model=StorageImageRepairResult)
def repair_image_access(
    current_user=Depends(require_admin), db: Session = Depends(get_db)
) -> StorageImageRepairResult:
    config = _get_or_create_config(db)
    if not config.access_key_id or not config.access_key_secret_encrypted or not config.bucket:
        return StorageImageRepairResult(repaired_count=0, message="请先完整填写 OSS 配置")
    try:
        documents = db.query(Document).all()
        refreshed_htmls, repaired_count = oss_client.refresh_document_image_urls(
            config,
            [document.current_html for document in documents],
        )
        for document, refreshed_html in zip(documents, refreshed_htmls):
            if document.current_html != refreshed_html:
                document.current_html = refreshed_html
                touch_document(document, current_user.id)
                if document.group:
                    touch_group(document.group, current_user.id)
        db.commit()
        return StorageImageRepairResult(
            repaired_count=repaired_count,
            message=f"已更新 {repaired_count} 张已导入图片的访问链接",
        )
    except oss_client.OSSNotConfiguredError as e:
        return StorageImageRepairResult(repaired_count=0, message=str(e))
    except oss2.exceptions.OssError as e:
        return StorageImageRepairResult(repaired_count=0, message=f"OSS 错误: {e.code} {e.message}")
    except Exception as e:  # noqa: BLE001 将未知上传/网络错误转为可见结果
        return StorageImageRepairResult(repaired_count=0, message=f"修复失败: {e}")
