"""Private storage and provider-content conversion for chat image attachments."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.chat_image_attachment import ChatImageAttachment
from app.models.storage_config import StorageConfig
from app.services import local_uploads, oss_client

MAX_CHAT_IMAGE_BYTES = 10 * 1024 * 1024
MAX_CHAT_IMAGES_PER_MESSAGE = 5
CHAT_IMAGE_DRAFT_TTL = timedelta(hours=24)
CHAT_IMAGE_TOKEN_COST = 1_024
SUPPORTED_CHAT_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

logger = logging.getLogger(__name__)


class ChatImageError(ValueError):
    pass


def _storage_if_configured(db: Session) -> StorageConfig | None:
    storage = db.query(StorageConfig).first()
    if not storage or not storage.endpoint or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        return None
    return storage


def _safe_filename(value: str, fallback_extension: str) -> str:
    name = PurePosixPath((value or "").replace("\\", "/")).name.strip()
    return name[:512] or f"image.{fallback_extension}"


def create_attachment(db: Session, *, document_id: int, uploader_id: int, data: bytes, filename: str) -> ChatImageAttachment:
    if len(data) > MAX_CHAT_IMAGE_BYTES:
        raise ChatImageError("图片不能超过 10MB")
    try:
        image = local_uploads.inspect_image(data)
    except local_uploads.LocalUploadError as exc:
        raise ChatImageError(str(exc)) from exc
    if image.content_type not in SUPPORTED_CHAT_IMAGE_TYPES:
        raise ChatImageError("聊天图片仅支持 PNG、JPG/JPEG、WEBP 或 GIF")

    attachment_id = str(uuid4())
    storage = _storage_if_configured(db)
    if storage is None:
        storage_mode = "local"
        object_key = local_uploads.chat_image_key(attachment_id, image.extension)
        try:
            local_uploads.save_bytes(object_key, data, lambda path: local_uploads.validate_image(path, image.content_type))
        except Exception as exc:  # noqa: BLE001
            raise ChatImageError("图片上传失败") from exc
    else:
        storage_mode = "oss"
        object_key = f"yibanpaiban/chat-images/{attachment_id}.{image.extension}"
        try:
            oss_client.put_object_bytes(storage, object_key, data, image.content_type)
        except Exception as exc:  # noqa: BLE001
            raise ChatImageError(f"图片上传失败: {exc}") from exc

    attachment = ChatImageAttachment(
        id=attachment_id,
        document_id=document_id,
        uploader_id=uploader_id,
        filename=_safe_filename(filename, image.extension),
        content_type=image.content_type,
        size=len(data),
        storage_mode=storage_mode,
        object_key=object_key,
    )
    db.add(attachment)
    return attachment


def duplicate_attachment(
    db: Session, *, source: ChatImageAttachment, uploader_id: int
) -> ChatImageAttachment:
    """Create a fresh draft attachment from a sent-message image.

    An image bound to an existing message is immutable history and cannot be
    attached to a second message. Re-reading and storing it as a new draft
    keeps the old transcript intact while allowing a historical request to be
    sent again.
    """
    return create_attachment(
        db,
        document_id=source.document_id,
        uploader_id=uploader_id,
        data=read_attachment_bytes(db, source),
        filename=source.filename,
    )


def read_attachment_bytes(db: Session, attachment: ChatImageAttachment) -> bytes:
    if attachment.storage_mode == "local":
        try:
            return local_uploads.local_path(attachment.object_key).read_bytes()
        except (OSError, local_uploads.LocalUploadError) as exc:
            raise ChatImageError("聊天图片已不存在") from exc
    storage = _storage_if_configured(db)
    if storage is None:
        raise ChatImageError("聊天图片存储不可用")
    try:
        return oss_client.get_object_bytes(storage, attachment.object_key)
    except Exception as exc:  # noqa: BLE001
        raise ChatImageError("聊天图片已不存在") from exc


def delete_attachment_object(db: Session, attachment: ChatImageAttachment) -> None:
    """Delete the durable object or fail without dropping its retry record."""
    try:
        if attachment.storage_mode == "local":
            local_uploads.delete(attachment.object_key)
            return
        storage = _storage_if_configured(db)
        if storage is None:
            raise ChatImageError("聊天图片存储不可用，无法删除")
        oss_client.delete_object(storage, attachment.object_key)
    except ChatImageError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ChatImageError("聊天图片存储删除失败，请稍后重试") from exc


def cleanup_expired_drafts(db: Session, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - CHAT_IMAGE_DRAFT_TTL
    rows = (
        db.query(ChatImageAttachment)
        .filter(ChatImageAttachment.message_id.is_(None), ChatImageAttachment.created_at < cutoff)
        .all()
    )
    deleted = 0
    for attachment in rows:
        try:
            delete_attachment_object(db, attachment)
        except ChatImageError:
            # Keep the database row so a later scheduled cleanup can retry
            # the object operation instead of creating an orphan silently.
            logger.warning("Unable to delete expired chat image attachment %s", attachment.id, exc_info=True)
            continue
        db.delete(attachment)
        deleted += 1
    if deleted:
        db.commit()
    return deleted


def delete_document_attachments(db: Session, document_id: int) -> None:
    for attachment in db.query(ChatImageAttachment).filter(ChatImageAttachment.document_id == document_id).all():
        delete_attachment_object(db, attachment)


def image_content_blocks(
    db: Session,
    attachments: Iterable[ChatImageAttachment],
    *,
    provider_type: str,
    include_images: bool,
) -> list[dict[str, Any]]:
    """Build provider-native blocks without persisting encoded image data."""
    if not include_images:
        return []
    blocks: list[dict[str, Any]] = []
    for attachment in attachments:
        encoded = base64.b64encode(read_attachment_bytes(db, attachment)).decode("ascii")
        if provider_type == "anthropic":
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": attachment.content_type, "data": encoded},
                }
            )
        else:
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{attachment.content_type};base64,{encoded}"},
                }
            )
    return blocks


def attachment_text_suffix(attachments: Iterable[ChatImageAttachment], include_images: bool) -> str:
    count = sum(1 for _ in attachments)
    if not count or include_images:
        return ""
    return f"\n\n[该消息包含 {count} 张图片；当前模型不支持读取图片。]"


def user_message_content(
    db: Session,
    text: str,
    attachments: Iterable[ChatImageAttachment],
    *,
    provider_type: str,
    include_images: bool,
) -> str | list[dict[str, Any]]:
    attachment_list = list(attachments)
    visible_text = text + attachment_text_suffix(attachment_list, include_images)
    image_blocks = image_content_blocks(
        db, attachment_list, provider_type=provider_type, include_images=include_images
    )
    if not image_blocks:
        return visible_text
    return [{"type": "text", "text": visible_text}, *image_blocks]
