from __future__ import annotations

from datetime import datetime, timezone
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
from app.models.user import User
from app.services import oss_client
from app.services.document_images import StoredDocumentImage


IMAGE_LIBRARY_SETTINGS_ID = 1


def get_or_create_settings(db: Session) -> ImageLibrarySettings:
    settings = db.get(ImageLibrarySettings, IMAGE_LIBRARY_SETTINGS_ID)
    if settings is None:
        settings = ImageLibrarySettings(id=IMAGE_LIBRARY_SETTINGS_ID, mode=ImageLibraryMode.PERSONAL)
        db.add(settings)
        db.flush()
    return settings


def library_mode(db: Session) -> ImageLibraryMode:
    return get_or_create_settings(db).mode


def refreshed_asset_url(db: Session, asset: ImageLibraryAsset) -> str:
    if asset.storage_mode != "oss":
        return asset.url
    storage = db.query(StorageConfig).first()
    if storage is None:
        return asset.url
    try:
        return oss_client.sign_read_url(storage, asset.object_key, oss_client.IMAGE_URL_EXPIRE_SECONDS)
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
