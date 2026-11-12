from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.image_generation import (
    GeneratedImageAsset,
    ImageGeneration,
    ImageLibraryAsset,
    ImageLibraryMode,
    ImageLibrarySettings,
    ImageLibrarySource,
)
from app.models.storage_config import StorageConfig
from app.models.document_import import DocumentImport, DocumentImportAsset, DocumentImportStatus
from app.models.document import Document
from app.models.user import User
from app.services import oss_client
from app.services.document_images import StoredDocumentImage
from app.services.document_images import store_tracked_document_image
from app.services import local_uploads


IMAGE_LIBRARY_SETTINGS_ID = 1
_OSS_IMPORT_PREFIX = "yibanpaiban/direct-imports/"
_SIGNED_URL_CACHE_TTL_SECONDS = 5 * 60
_SIGNED_URL_CACHE_MAX_ITEMS = 512
_signed_read_url_cache: OrderedDict[tuple[int, str, str], tuple[float, str]] = OrderedDict()
_signed_read_url_cache_lock = Lock()


class _ImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.append(source)


def get_or_create_settings(db: Session) -> ImageLibrarySettings:
    settings = db.get(ImageLibrarySettings, IMAGE_LIBRARY_SETTINGS_ID)
    if settings is None:
        settings = ImageLibrarySettings(id=IMAGE_LIBRARY_SETTINGS_ID, mode=ImageLibraryMode.PERSONAL)
        db.add(settings)
        db.flush()
    return settings


def library_mode(db: Session) -> ImageLibraryMode:
    return get_or_create_settings(db).mode


def _cached_signed_read_url(storage: StorageConfig, object_key: str) -> str:
    """Avoid generating a different private URL for every gallery refresh.

    The underlying image URLs are intentionally long-lived, but a fresh
    signature changes the query string and prevents the browser from reusing
    its image cache. Keep the server-issued URL stable for a short interval;
    storage edits invalidate the cache through ``updated_at``.
    """
    cache_key = (storage.id, storage.updated_at.isoformat() if storage.updated_at else "", object_key)
    now = monotonic()
    with _signed_read_url_cache_lock:
        cached = _signed_read_url_cache.get(cache_key)
        if cached and cached[0] > now:
            _signed_read_url_cache.move_to_end(cache_key)
            return cached[1]

    url = oss_client.sign_read_url(storage, object_key, oss_client.IMAGE_URL_EXPIRE_SECONDS)
    with _signed_read_url_cache_lock:
        _signed_read_url_cache[cache_key] = (now + _SIGNED_URL_CACHE_TTL_SECONDS, url)
        _signed_read_url_cache.move_to_end(cache_key)
        while len(_signed_read_url_cache) > _SIGNED_URL_CACHE_MAX_ITEMS:
            _signed_read_url_cache.popitem(last=False)
    return url


def refreshed_asset_url(db: Session, asset: ImageLibraryAsset) -> str:
    if asset.storage_mode != "oss":
        return asset.url
    storage = db.query(StorageConfig).first()
    if storage is None:
        return asset.url
    try:
        return _cached_signed_read_url(storage, asset.object_key)
    except Exception:
        return asset.url


def asset_payload(db: Session, asset: ImageLibraryAsset, user: User, mode: ImageLibraryMode | None = None) -> dict:
    active_mode = mode or library_mode(db)
    owner = db.get(User, asset.owner_id)
    return {
        "id": asset.id,
        "owner_id": asset.owner_id,
        "owner_name": (owner.display_name or owner.username) if owner else "已删除用户",
        "document_id": asset.document_id,
        "generation_id": asset.generation_id,
        "generated_asset_id": asset.generated_asset_id,
        "name": asset.name,
        "source": asset.source.value if hasattr(asset.source, "value") else str(asset.source),
        "url": refreshed_asset_url(db, asset),
        "content_type": asset.content_type,
        "size": asset.size,
        "width": asset.width,
        "height": asset.height,
        "is_shared": bool(asset.is_shared),
        "can_manage": active_mode == ImageLibraryMode.SHARED or asset.owner_id == user.id,
        "created_at": asset.created_at,
        # Compatibility for assets inserted through the legacy nullable
        # ``updated_at`` column before its MySQL default was repaired.
        "updated_at": asset.updated_at or asset.created_at,
    }


def create_library_asset(
    db: Session,
    *,
    owner_id: int,
    stored: StoredDocumentImage,
    content_type: str,
    size: int,
    width: int,
    height: int,
    name: str,
    source: ImageLibrarySource,
    document_id: int | None = None,
    generation_id: str = "",
    generated_asset_id: str = "",
    is_shared: bool | None = None,
) -> ImageLibraryAsset:
    if generated_asset_id:
        existing = db.query(ImageLibraryAsset).filter(ImageLibraryAsset.generated_asset_id == generated_asset_id).first()
        if existing is not None:
            return existing
    now = datetime.now(timezone.utc)
    asset = ImageLibraryAsset(
        id=str(uuid4()),
        owner_id=owner_id,
        document_id=document_id,
        generation_id=generation_id,
        generated_asset_id=generated_asset_id,
        name=(name.strip() or "图片")[:256],
        source=source,
        object_key=stored.object_key,
        storage_mode=stored.storage_mode,
        url=stored.url,
        content_type=content_type,
        size=size,
        width=width,
        height=height,
        is_shared=library_mode(db) == ImageLibraryMode.SHARED if is_shared is None else is_shared,
        updated_at=now,
    )
    db.add(asset)
    return asset


def ensure_generated_asset_in_library(
    db: Session,
    generation: ImageGeneration,
    generated: GeneratedImageAsset,
    *,
    is_shared: bool | None = None,
) -> ImageLibraryAsset:
    return create_library_asset(
        db,
        owner_id=generation.user_id,
        document_id=generation.document_id,
        generation_id=generation.id,
        generated_asset_id=generated.id,
        name=(generated.revised_prompt or generation.prompt or "AI 生成图片")[:256],
        source=ImageLibrarySource.AI,
        stored=StoredDocumentImage(
            url=generated.url,
            object_key=generated.object_key,
            storage_mode=generated.storage_mode,
        ),
        content_type=generated.content_type,
        size=generated.size,
        width=generated.width,
        height=generated.height,
        is_shared=is_shared,
    )


def soft_delete(asset: ImageLibraryAsset) -> None:
    asset.deleted_at = datetime.now(timezone.utc)


def _is_temporary_import_key(object_key: str) -> bool:
    return object_key.startswith(("local/direct-imports/", _OSS_IMPORT_PREFIX))


def _replace_image_url_reference(html: str, old_url: str, new_url: str) -> str:
    # HTMLParser decodes entities in src attributes. Match the encoded form
    # too, or signed URLs containing &amp; keep re-registering old imports.
    return html.replace(escape(old_url, quote=True), escape(new_url, quote=True)).replace(old_url, new_url)


def _replace_document_import_image(
    db: Session,
    document: Document | None,
    old_key: str,
    old_url: str,
    stored: StoredDocumentImage,
    storage: StorageConfig | None,
) -> None:
    if document is None or not document.current_html:
        return
    html = document.current_html
    # Preserve crop/source attributes and any other references that use the
    # exact URL persisted during import.
    if old_url:
        html = _replace_image_url_reference(html, old_url, stored.url)
    if old_key.startswith("local/direct-imports/"):
        import_asset = db.query(DocumentImportAsset).filter(DocumentImportAsset.object_key == old_key).first()
        if import_asset is not None:
            html = _replace_image_url_reference(html, f"/api/documents/import-assets/{import_asset.id}", stored.url)
    elif storage is not None:
        parser = _ImageSourceParser()
        parser.feed(html)
        parser.close()
        for source in parser.sources:
            if oss_client.storage_object_key_for_url(storage, source) == old_key:
                html = _replace_image_url_reference(html, source, stored.url)
    document.current_html = html


def _promote_temporary_library_asset(
    db: Session,
    asset: ImageLibraryAsset,
    document: Document | None,
    storage: StorageConfig | None,
) -> bool:
    """Copy a direct-import object into durable image storage exactly once."""
    if not _is_temporary_import_key(asset.object_key):
        return False
    if document is not None:
        from app.models.agent_run import AgentRun, AgentRunStatus
        document = db.query(Document).filter(Document.id == document.id).populate_existing().with_for_update().first()
        if document is not None and db.query(AgentRun.id).filter(
            AgentRun.document_id == document.id,
            AgentRun.status.in_([AgentRunStatus.PENDING, AgentRunStatus.RUNNING,
                                AgentRunStatus.WAITING_FOR_INPUT, AgentRunStatus.CANCELLING]),
        ).with_for_update().first() is not None:
            return False
    if asset.storage_mode == "oss":
        if storage is None:
            return False
        try:
            data = oss_client.get_object_bytes(storage, asset.object_key)
        except Exception:
            return False
    else:
        try:
            data = local_uploads.local_path(asset.object_key).read_bytes()
        except (OSError, local_uploads.LocalUploadError):
            return False
    try:
        image = local_uploads.inspect_image(data)
        stored = store_tracked_document_image(db, data, asset.name or "image")
    except (local_uploads.LocalUploadError, OSError, ValueError):
        return False
    old_key = asset.object_key
    old_url = asset.url
    asset.object_key = stored.object_key
    asset.storage_mode = stored.storage_mode
    asset.url = stored.url
    asset.content_type = image.content_type
    asset.size = len(data)
    asset.width = image.width
    asset.height = image.height
    _replace_document_import_image(db, document, old_key, old_url, stored, storage)
    # The caller commits the metadata update. The old direct-import object is
    # intentionally left for the import cleanup path/lifecycle to remove.
    return True


def backfill_generated_assets(db: Session) -> int:
    rows = (
        db.query(GeneratedImageAsset, ImageGeneration)
        .join(ImageGeneration, ImageGeneration.id == GeneratedImageAsset.generation_id)
        .outerjoin(ImageLibraryAsset, ImageLibraryAsset.generated_asset_id == GeneratedImageAsset.id)
        .filter(ImageLibraryAsset.id.is_(None))
        .all()
    )
    for generated, generation in rows:
        ensure_generated_asset_in_library(db, generation, generated, is_shared=False)
    if rows:
        db.commit()
    return len(rows)


def backfill_imported_assets(db: Session) -> int:
    """Register images from completed PDF/Word imports made before gallery sync."""
    storage = db.query(StorageConfig).first()
    promoted = 0
    temporary_assets = (
        db.query(ImageLibraryAsset)
        .filter(
            ImageLibraryAsset.deleted_at.is_(None),
            ImageLibraryAsset.object_key.startswith("local/direct-imports/")
            | ImageLibraryAsset.object_key.startswith(_OSS_IMPORT_PREFIX),
        )
        .all()
    )
    for asset in temporary_assets:
        document = db.get(Document, asset.document_id) if asset.document_id else None
        if _promote_temporary_library_asset(db, asset, document, storage):
            promoted += 1

    rows = (
        db.query(DocumentImportAsset, DocumentImport, Document)
        .join(DocumentImport, DocumentImport.id == DocumentImportAsset.import_id)
        .join(Document, Document.id == DocumentImport.document_id)
        .outerjoin(ImageLibraryAsset, ImageLibraryAsset.object_key == DocumentImportAsset.object_key)
        .filter(
            DocumentImport.status == DocumentImportStatus.COMPLETED,
            DocumentImportAsset.id.is_not(None),
            ImageLibraryAsset.id.is_(None),
        )
        .all()
    )
    # Promotions must be committed even when every import is already in the
    # library; otherwise the next startup downloads and copies them again.
    created = 0
    for asset, _import_session, document in rows:
        # A completed Word import may retain parser-only crop/source assets;
        # only promote images that survived into the article HTML.
        if local_uploads.is_local_key(asset.object_key):
            if f"/api/documents/import-assets/{asset.id}" not in (document.current_html or ""):
                continue
        elif storage is None:
            continue
        else:
            parser = _ImageSourceParser()
            parser.feed(document.current_html or "")
            parser.close()
            if not any(oss_client.storage_object_key_for_url(storage, source) == asset.object_key for source in parser.sources):
                continue
        width = height = 0
        if local_uploads.is_local_key(asset.object_key):
            try:
                image = local_uploads.validate_image(local_uploads.local_path(asset.object_key), asset.content_type)
                width, height = image.width, image.height
            except (local_uploads.LocalUploadError, OSError):
                continue
            stored = StoredDocumentImage(
                url=f"/api/documents/import-assets/{asset.id}",
                object_key=asset.object_key,
                storage_mode="local",
            )
        elif storage is not None:
            try:
                stored = StoredDocumentImage(
                    url=oss_client.sign_read_url(storage, asset.object_key, oss_client.IMAGE_URL_EXPIRE_SECONDS),
                    object_key=asset.object_key,
                    storage_mode="oss",
                )
            except Exception:
                continue
        else:
            continue
        library_asset = create_library_asset(
            db,
            owner_id=document.owner_id,
            document_id=document.id,
            name=asset.filename or "图片",
            source=ImageLibrarySource.UPLOAD,
            stored=stored,
            content_type=asset.content_type,
            size=asset.size,
            width=width,
            height=height,
        )
        # Finish newly registered imports in this pass as well. Failed copies
        # keep their temporary key and remain eligible for the next startup.
        _promote_temporary_library_asset(db, library_asset, document, storage)
        created += 1
    if created or promoted:
        db.commit()
    return created + promoted
