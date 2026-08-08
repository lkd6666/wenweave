"""Materialize external and reusable component images into document-owned storage."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.storage_config import StorageConfig
from app.models.template_library import TemplateImageAsset
from app.services import local_uploads, oss_client
from app.services.document_images import (
    DocumentImageStorageError,
    StoredDocumentImage,
    delete_tracked_document_image,
    store_tracked_document_image,
)
from app.services.external_fetch import PublicFetchError, fetch_public_image
from app.services.image_localization import (
    ImageLocalizationError,
    ImageLocalizationResult,
    StoredImage,
    localize_html_images,
)
from app.services.template_library import ASSET_URL_PREFIX, TemplateLibraryError, read_asset_bytes


MAX_DOCUMENT_LOCALIZATION_IMAGES = 400
MAX_DOCUMENT_LOCALIZATION_BYTES = 50 * 1024 * 1024
_TEMPLATE_ASSET_ID = re.compile(r"^/api/template-library/assets/([0-9a-fA-F-]{36})$")
_LOCAL_DOCUMENT_PREFIXES = (
    "/api/documents/local-images/",
    "/api/documents/import-assets/",
)


def _storage_if_configured(db: Session) -> StorageConfig | None:
    storage = db.query(StorageConfig).first()
    if not storage or not storage.endpoint or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        return None
    return storage


def _template_asset_id(source: str) -> str | None:
    path = urlsplit(source).path if source.lower().startswith(("http://", "https://")) else source
    match = _TEMPLATE_ASSET_ID.fullmatch(path)
    return match.group(1) if match else None


def _is_document_local_source(db: Session, source: str) -> bool:
    path = urlsplit(source).path if source.lower().startswith(("http://", "https://")) else source
    if path.startswith(_LOCAL_DOCUMENT_PREFIXES):
        return True
    storage = _storage_if_configured(db)
    return bool(storage and oss_client.storage_object_key_for_url(storage, source))


async def localize_document_html(db: Session, document: Document, html: str) -> ImageLocalizationResult:
    """Copy each non-document image into article storage without mutating the document."""
    async def load_image(source: str, client: httpx.AsyncClient):
        asset_id = _template_asset_id(source)
        if asset_id:
            asset = db.get(TemplateImageAsset, asset_id)
            if asset is None:
                raise ImageLocalizationError("组件图片不存在")
            try:
                data = read_asset_bytes(db, asset)
                return data, local_uploads.inspect_image(data)
            except (TemplateLibraryError, local_uploads.LocalUploadError) as exc:
                raise ImageLocalizationError(str(exc) or "组件图片不存在") from exc
        try:
            return await fetch_public_image(client, source)
        except PublicFetchError as exc:
            raise ImageLocalizationError(str(exc)) from exc

    def store_image(data: bytes, _image: local_uploads.ImageInfo, source: str) -> StoredImage:
        try:
            persisted = store_tracked_document_image(db, data, f"localized-{source.rsplit('/', 1)[-1] or 'image'}")
            return StoredImage(url=persisted.url, handle=persisted)
        except DocumentImageStorageError as exc:
            raise ImageLocalizationError(str(exc)) from exc

    def cleanup_image(persisted: StoredImage) -> None:
        handle = persisted.handle
        if isinstance(handle, StoredDocumentImage):
            delete_tracked_document_image(db, handle)

    return await localize_html_images(
        html,
        load_image=load_image,
        store_image=store_image,
        cleanup_image=cleanup_image,
        is_local_source=lambda source: _is_document_local_source(db, source),
        max_images=MAX_DOCUMENT_LOCALIZATION_IMAGES,
        max_total_bytes=MAX_DOCUMENT_LOCALIZATION_BYTES,
    )


def cleanup_document_localization(db: Session, result: ImageLocalizationResult) -> None:
    for persisted in reversed(result.stored_images):
        if isinstance(persisted.handle, StoredDocumentImage):
            delete_tracked_document_image(db, persisted.handle)
