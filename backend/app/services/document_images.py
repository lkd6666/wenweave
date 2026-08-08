"""Shared persistence for validated article images."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.storage_config import StorageConfig
from app.services import local_uploads, oss_client


MAX_DOCUMENT_IMAGE_BYTES = 10 * 1024 * 1024


class DocumentImageStorageError(ValueError):
    """An image cannot be safely stored for use in an article."""


@dataclass(frozen=True)
class StoredDocumentImage:
    url: str
    object_key: str
    storage_mode: str


def _storage_if_configured(db: Session) -> StorageConfig | None:
    storage = db.query(StorageConfig).first()
    if not storage or not storage.endpoint or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        return None
    return storage


def store_document_image(db: Session, data: bytes, filename: str = "image") -> str:
    """Validate and persist image bytes using the configured durable backend."""
    if len(data) > MAX_DOCUMENT_IMAGE_BYTES:
        raise DocumentImageStorageError("图片不能超过 10MB")
    try:
        image = local_uploads.inspect_image(data)
        object_name = f"{filename.rsplit('.', 1)[0] or 'image'}.{image.extension}"
        storage = _storage_if_configured(db)
        if storage is not None:
            return oss_client.upload_bytes(storage, data, object_name, image.content_type)
        key = local_uploads.manual_image_key(image.extension)
        local_uploads.save_bytes(key, data, lambda path: local_uploads.validate_image(path, image.content_type))
        return f"/api/documents/local-images/{key.rsplit('/', 1)[-1]}"
    except (local_uploads.LocalUploadError, oss_client.OSSNotConfiguredError, oss_client.ObjectStorageError) as exc:
        raise DocumentImageStorageError(str(exc)) from exc


def store_tracked_document_image(db: Session, data: bytes, filename: str = "image") -> StoredDocumentImage:
    """Persist one article image and retain enough metadata for compensation."""
    if len(data) > MAX_DOCUMENT_IMAGE_BYTES:
        raise DocumentImageStorageError("图片不能超过 10MB")
    try:
        image = local_uploads.inspect_image(data)
        storage = _storage_if_configured(db)
        if storage is None:
            object_key = local_uploads.manual_image_key(image.extension)
            local_uploads.save_bytes(object_key, data, lambda path: local_uploads.validate_image(path, image.content_type))
            return StoredDocumentImage(
                url=f"/api/documents/local-images/{object_key.rsplit('/', 1)[-1]}",
                object_key=object_key,
                storage_mode="local",
            )
        object_key = f"yibanpaiban/{datetime.now(timezone.utc):%Y%m%d}/{uuid4().hex}.{image.extension}"
        oss_client.put_object_bytes(storage, object_key, data, image.content_type)
        return StoredDocumentImage(
            url=oss_client.sign_read_url(storage, object_key, oss_client.IMAGE_URL_EXPIRE_SECONDS),
            object_key=object_key,
            storage_mode="oss",
        )
    except (local_uploads.LocalUploadError, oss_client.OSSNotConfiguredError, oss_client.ObjectStorageError) as exc:
        raise DocumentImageStorageError(str(exc)) from exc


def delete_tracked_document_image(db: Session, image: StoredDocumentImage) -> None:
    """Best-effort cleanup for an image whose parent HTML update did not complete."""
    try:
        if image.storage_mode == "local":
            local_uploads.delete(image.object_key)
            return
        storage = _storage_if_configured(db)
        if storage is not None:
            oss_client.delete_object(storage, image.object_key)
    except Exception:
        return
