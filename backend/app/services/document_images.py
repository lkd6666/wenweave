"""Shared persistence for validated article images."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.storage_config import StorageConfig
from app.services import local_uploads, oss_client


MAX_DOCUMENT_IMAGE_BYTES = 10 * 1024 * 1024


class DocumentImageStorageError(ValueError):
    """An image cannot be safely stored for use in an article."""


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
