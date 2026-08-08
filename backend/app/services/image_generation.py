"""Provider-normalised, durable text-to-image generation."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session, joinedload

from app.core.crypto import decrypt_secret
from app.db.session import SessionLocal
from app.models.ai_image_model import AIImageModel
from app.models.image_generation import (
    GeneratedImageAsset,
    ImageGeneration,
    ImageGenerationPurpose,
    ImageGenerationSource,
    ImageGenerationStatus,
)
from app.services import local_uploads
from app.services.document_images import (
    DocumentImageStorageError,
    StoredDocumentImage,
    delete_tracked_document_image,
    store_tracked_document_image,
)
from app.services.external_fetch import PublicFetchError, fetch_public_image


IMAGE_GENERATION_TIMEOUT_SECONDS = 180.0
POLL_INTERVAL_SECONDS = 1.5
MAX_POLL_ATTEMPTS = 80
UNUSED_ASSET_TTL = timedelta(days=7)
_DASHSCOPE_RESULT_HOST_RE = re.compile(
    r"^(?:dashscope-result-[a-z0-9-]+\.oss-cn-[a-z0-9-]+\.aliyuncs\.com|"
    r"dashscope-[a-z0-9-]+\.oss-accelerate\.aliyuncs\.com)$"
)


class ImageGenerationError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderImage:
    data: bytes | None = None
    url: str = ""
    revised_prompt: str = ""


@dataclass(frozen=True)
class ProviderGenerationResult:
    images: tuple[ProviderImage, ...]
    usage: dict[str, Any]
    provider_task_id: str = ""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
    """Extract a concise, user-readable detail from an HTTP error response."""
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            # DashScope / OpenAI style: {"message": "..."} or {"error": {"message": "..."}}
            msg = (
                body.get("message")
                or (body.get("error") or {}).get("message")
                or body.get("code")
                or ""
            )
            if msg:
                return f"HTTP {exc.response.status_code}: {str(msg)[:300]}"
    except Exception:  # noqa: BLE001
        pass
    text = exc.response.text[:300].strip()
    return f"HTTP {exc.response.status_code}" + (f": {text}" if text else "")


def _size_for(protocol: str, aspect_ratio: str) -> str:
    if protocol == "openai_images":
        return {"square": "1024x1024", "portrait": "1024x1536", "landscape": "1536x1024"}[aspect_ratio]
    if protocol == "dashscope_images":
        return {"square": "1024*1024", "portrait": "720*1280", "landscape": "1280*720"}[aspect_ratio]
    return {"square": "1024x1024", "portrait": "768x1024", "landscape": "1024x768"}[aspect_ratio]


def _decode_base64(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None


def _images_from_payload(payload: dict[str, Any]) -> tuple[ProviderImage, ...]:
    roots: list[object] = [payload.get("data"), payload.get("results")]
    output = payload.get("output")
    if isinstance(output, dict):
        roots.extend([output.get("results"), output.get("data")])
        # DashScope's 2.7 image models return OpenAI-style message content:
        # output.choices[].message.content[].image.
        choices = output.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    roots.append(message.get("content"))
    for root in roots:
        if not isinstance(root, list):
            continue
        images: list[ProviderImage] = []
        for item in root:
            if not isinstance(item, dict):
                continue
            data = _decode_base64(item.get("b64_json") or item.get("base64") or item.get("image"))
            url = str(item.get("url") or item.get("image_url") or "")
            # Native DashScope content items use {"image": "https://..."}
            # while OpenAI uses url/b64_json.  Treat image as a URL when it is
            # not base64 or a data URI.
            if not data and not url:
                image_value = item.get("image")
                if isinstance(image_value, str) and image_value.startswith(("http://", "https://")):
                    url = image_value
            if data or url:
                images.append(ProviderImage(data=data, url=url, revised_prompt=str(item.get("revised_prompt") or "")))
        if images:
            return tuple(images)
    return ()


async def _openai_images(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: AIImageModel,
    generation: ImageGeneration,
    *,
    size_protocol: str = "openai_images",
    send_quality: bool = True,
) -> ProviderGenerationResult:
    payload: dict[str, Any] = {
        "model": model.model_name,
        "prompt": generation.prompt,
        "n": generation.quantity,
        "size": _size_for(size_protocol, generation.aspect_ratio),
    }
    if send_quality and generation.quality and generation.quality != "auto":
        payload["quality"] = generation.quality
    response = await client.post(
        _normalise_url(base_url, "images/generations"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ImageGenerationError(_http_error_detail(exc)) from exc
    body = response.json()
    if not isinstance(body, dict):
        raise ImageGenerationError("图片模型返回格式无效")
    images = _images_from_payload(body)
    if not images:
        raise ImageGenerationError("图片模型未返回可用图片")
    return ProviderGenerationResult(images=images, usage=body.get("usage") if isinstance(body.get("usage"), dict) else {})


async def _dashscope_images(
    client: httpx.AsyncClient, base_url: str, api_key: str, model: AIImageModel, generation: ImageGeneration
) -> ProviderGenerationResult:
    model_name = model.model_name.lower()
    # Token Plan's configured URL is an OpenAI-compatible prefix, but its
    # image models are exposed on the DashScope native API at the same host.
    # Strip /compatible-mode/v1 and address the documented /api/v1 route.
    if "/compatible-mode/" in base_url.lower():
        api_base = base_url.split("/compatible-mode/", 1)[0].rstrip("/") + "/api/v1"
    else:
        api_base = base_url.rstrip("/")

    is_wan27 = model_name in {"wan2.7-image", "wan2.7-image-pro"}
    if is_wan27:
        endpoint = _normalise_url(api_base, "services/aigc/image-generation/generation")
        payload: dict[str, Any] = {
            "model": model.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": generation.prompt}],
                    }
                ]
            },
            "parameters": {
                "size": _size_for("dashscope_images", generation.aspect_ratio),
                "n": generation.quantity,
                "watermark": False,
                "thinking_mode": False,
            },
        }
    else:
        endpoint = _normalise_url(api_base, "services/aigc/text2image/image-synthesis")
        payload = {
            "model": model.model_name,
            "input": {"prompt": generation.prompt},
            "parameters": {"size": _size_for("dashscope_images", generation.aspect_ratio), "n": generation.quantity},
        }
    response = await client.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        },
        json=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ImageGenerationError(_http_error_detail(exc)) from exc
    body = response.json()
    if not isinstance(body, dict):
        raise ImageGenerationError("百炼图片任务返回格式无效")
    output = body.get("output") if isinstance(body.get("output"), dict) else {}
    task_id = str(output.get("task_id") or body.get("task_id") or "")
    images = _images_from_payload(body)
    if images:
        return ProviderGenerationResult(images=images, usage=body.get("usage") if isinstance(body.get("usage"), dict) else {}, provider_task_id=task_id)
    if not task_id:
        raise ImageGenerationError(str(body.get("message") or "百炼没有返回图片任务"))
    task_url = _normalise_url(api_base, f"tasks/{task_id}")
    for _ in range(MAX_POLL_ATTEMPTS):
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        task_response = await client.get(task_url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            task_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ImageGenerationError(_http_error_detail(exc)) from exc
        task_body = task_response.json()
        if not isinstance(task_body, dict):
            continue
        task_output = task_body.get("output") if isinstance(task_body.get("output"), dict) else {}
        status = str(task_output.get("task_status") or task_body.get("status") or "").upper()
        images = _images_from_payload(task_body)
        if images:
            return ProviderGenerationResult(
                images=images,
                usage=task_body.get("usage") if isinstance(task_body.get("usage"), dict) else {},
                provider_task_id=task_id,
            )
        if status in {"FAILED", "CANCELED", "CANCELLED"}:
            raise ImageGenerationError(str(task_output.get("message") or task_body.get("message") or "百炼图片任务失败"))
        if status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
            raise ImageGenerationError("百炼图片任务已完成，但没有返回可用图片")
    raise ImageGenerationError("百炼图片生成超时")


async def _volcengine_ark_images(
    client: httpx.AsyncClient, base_url: str, api_key: str, model: AIImageModel, generation: ImageGeneration
) -> ProviderGenerationResult:
    payload: dict[str, Any] = {
        "model": model.model_name,
        "prompt": generation.prompt,
        "n": generation.quantity,
        "size": _size_for("volcengine_ark_images", generation.aspect_ratio),
        "response_format": "b64_json",
    }
    if generation.quality and generation.quality != "auto":
        payload["quality"] = generation.quality
    response = await client.post(
        _normalise_url(base_url, "images/generations"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ImageGenerationError(_http_error_detail(exc)) from exc
    body = response.json()
    if not isinstance(body, dict):
        raise ImageGenerationError("方舟图片模型返回格式无效")
    images = _images_from_payload(body)
    if not images:
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raise ImageGenerationError(str(error.get("message") or body.get("message") or "方舟未返回可用图片"))
    return ProviderGenerationResult(images=images, usage=body.get("usage") if isinstance(body.get("usage"), dict) else {})


async def _call_provider(model: AIImageModel, generation: ImageGeneration) -> ProviderGenerationResult:
    provider = model.provider
    protocol = str(provider.image_protocol or "")
    base_url = str(provider.image_base_url or "").strip()
    if not protocol or not base_url:
        raise ImageGenerationError("该 Provider 尚未配置图片生成端点")
    api_key = decrypt_secret(provider.api_key_encrypted)
    timeout = httpx.Timeout(IMAGE_GENERATION_TIMEOUT_SECONDS, connect=20)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        if protocol == "openai_images":
            return await _openai_images(client, base_url, api_key, model, generation)
        if protocol == "dashscope_images":
            return await _dashscope_images(client, base_url, api_key, model, generation)
        if protocol == "volcengine_ark_images":
            return await _volcengine_ark_images(client, base_url, api_key, model, generation)
    raise ImageGenerationError("不支持的图片生成协议")


def _trusted_provider_image_hosts(image_url: str) -> frozenset[str]:
    """Trust the narrow DashScope result host family for the desktop proxy only."""
    try:
        host = (urlsplit(image_url).hostname or "").lower().rstrip(".")
    except ValueError:
        return frozenset()
    return frozenset({host}) if _DASHSCOPE_RESULT_HOST_RE.fullmatch(host) else frozenset()


async def _materialize_image(image: ProviderImage) -> bytes:
    if image.data is not None:
        return image.data
    if not image.url:
        raise ImageGenerationError("图片模型没有返回图片内容")
    try:
        timeout = httpx.Timeout(30, connect=10)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            data, _ = await fetch_public_image(
                client,
                image.url,
                trusted_proxy_hosts=_trusted_provider_image_hosts(image.url),
            )
            return data
    except (PublicFetchError, httpx.HTTPError) as exc:
        raise ImageGenerationError(f"下载模型生成图片失败：{exc}") from exc


def generation_payload(generation: ImageGeneration) -> dict[str, Any]:
    try:
        usage = json.loads(generation.usage_json or "{}")
    except json.JSONDecodeError:
        usage = {}
    return {
        "id": generation.id,
        "document_id": generation.document_id,
        "session_id": generation.session_id,
        "model_id": generation.model_id,
        "source": generation.source.value,
        "purpose": generation.purpose.value,
        "prompt": generation.prompt,
        "quantity": generation.quantity,
        "aspect_ratio": generation.aspect_ratio,
        "quality": generation.quality,
        "anchor_block_id": generation.anchor_block_id,
        "direct_insert": generation.direct_insert,
        "status": generation.status.value,
        "error_message": generation.error_message,
        "usage": usage if isinstance(usage, dict) else {},
        "created_at": generation.created_at.isoformat() if generation.created_at else None,
        "updated_at": generation.updated_at.isoformat() if generation.updated_at else None,
        "finished_at": generation.finished_at.isoformat() if generation.finished_at else None,
        "assets": [
            {
                "id": asset.id,
                "generation_id": asset.generation_id,
                "url": asset.url,
                "content_type": asset.content_type,
                "size": asset.size,
                "width": asset.width,
                "height": asset.height,
                "revised_prompt": asset.revised_prompt,
                "is_applied": asset.is_applied,
                "applied_at": asset.applied_at.isoformat() if asset.applied_at else None,
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
            }
            for asset in generation.assets
        ],
    }


def create_generation(
    db: Session,
    *,
    document_id: int,
    session_id: int | None,
    model_id: int,
    user_id: int,
    source: ImageGenerationSource,
    purpose: ImageGenerationPurpose,
    prompt: str,
    quantity: int,
    aspect_ratio: str,
    quality: str,
    anchor_block_id: str = "",
    direct_insert: bool = False,
) -> ImageGeneration:
    generation = ImageGeneration(
        id=str(uuid4()),
        document_id=document_id,
        session_id=session_id,
        model_id=model_id,
        user_id=user_id,
        source=source,
        purpose=purpose,
        prompt=prompt,
        quantity=quantity,
        aspect_ratio=aspect_ratio,
        quality=quality,
        anchor_block_id=anchor_block_id,
        direct_insert=direct_insert,
        status=ImageGenerationStatus.PENDING,
    )
    db.add(generation)
    db.flush()
    return generation


async def run_generation(generation_id: str) -> None:
    db = SessionLocal()
    stored: list[StoredDocumentImage] = []
    created_asset_count = 0
    try:
        generation = (
            db.query(ImageGeneration)
            .options(joinedload(ImageGeneration.model).joinedload(AIImageModel.provider), joinedload(ImageGeneration.assets))
            .filter(ImageGeneration.id == generation_id)
            .with_for_update()
            .first()
        )
        if generation is None or generation.status != ImageGenerationStatus.PENDING:
            return
        if generation.cancel_requested:
            generation.status = ImageGenerationStatus.CANCELLED
            generation.finished_at = utcnow()
            db.commit()
            return
        generation.status = ImageGenerationStatus.RUNNING
        db.commit()
        result = await _call_provider(generation.model, generation)
        generation = db.get(ImageGeneration, generation_id)
        if generation is None:
            return
        generation.provider_task_id = result.provider_task_id
        if generation.cancel_requested:
            generation.status = ImageGenerationStatus.CANCELLED
            generation.finished_at = utcnow()
            db.commit()
            return
        for index, image in enumerate(result.images[: generation.quantity], start=1):
            data = await _materialize_image(image)
            stored_image = store_tracked_document_image(db, data, f"generated-{generation.id}-{index}.png")
            stored.append(stored_image)
            inspected = local_uploads.inspect_image(data)
            db.refresh(generation)
            if generation.cancel_requested:
                delete_tracked_document_image(db, stored_image)
                continue
            db.add(
                GeneratedImageAsset(
                    id=str(uuid4()),
                    generation_id=generation.id,
                    object_key=stored_image.object_key,
                    storage_mode=stored_image.storage_mode,
                    url=stored_image.url,
                    content_type=inspected.content_type,
                    size=len(data),
                    width=inspected.width,
                    height=inspected.height,
                    revised_prompt=image.revised_prompt,
                )
            )
            created_asset_count += 1
        if generation.cancel_requested:
            generation.status = ImageGenerationStatus.CANCELLED
        elif created_asset_count == 0:
            raise ImageGenerationError("图片生成没有产生可保存的结果")
        else:
            generation.status = ImageGenerationStatus.SUCCEEDED
            generation.usage_json = json.dumps(result.usage, ensure_ascii=False, separators=(",", ":"))
        generation.finished_at = utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - error is persisted for user retry.
        db.rollback()
        for stored_image in stored:
            try:
                delete_tracked_document_image(db, stored_image)
            except Exception:
                # Storage cleanup is best effort; the durable task error is
                # still recorded below and the scheduled asset sweep can
                # remove any row that was committed before the failure.
                pass
        generation = db.get(ImageGeneration, generation_id)
        if generation is not None:
            generation.status = ImageGenerationStatus.FAILED
            generation.error_message = str(exc)[:2048] or "图片生成失败"
            generation.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def start_generation(generation_id: str) -> asyncio.Task[None]:
    return asyncio.create_task(run_generation(generation_id))


def run_generation_sync(generation_id: str) -> None:
    """ToolNode executes synchronous tools in a worker thread."""
    asyncio.run(run_generation(generation_id))


def recover_pending_generations() -> list[str]:
    """Return safe-to-retry pending jobs after process restart.

    Running requests are deliberately failed instead of replayed: synchronous
    provider calls may already have incurred cost and cannot be idempotently
    reconstructed after a worker crash.
    """
    db = SessionLocal()
    try:
        running = db.query(ImageGeneration).filter(ImageGeneration.status == ImageGenerationStatus.RUNNING).all()
        for generation in running:
            generation.status = ImageGenerationStatus.FAILED
            generation.error_message = "服务重启中断了图片生成，请手动重试以避免重复扣费"
            generation.finished_at = utcnow()
        pending = [row.id for row in db.query(ImageGeneration.id).filter(ImageGeneration.status == ImageGenerationStatus.PENDING).all()]
        db.commit()
        return pending
    finally:
        db.close()


def cleanup_unused_assets(db: Session) -> int:
    cutoff = utcnow() - UNUSED_ASSET_TTL
    assets = (
        db.query(GeneratedImageAsset)
        .filter(GeneratedImageAsset.is_applied.is_(False), GeneratedImageAsset.created_at < cutoff)
        .all()
    )
    removed = 0
    for asset in assets:
        delete_tracked_document_image(
            db,
            StoredDocumentImage(url=asset.url, object_key=asset.object_key, storage_mode=asset.storage_mode),
        )
        db.delete(asset)
        removed += 1
    if removed:
        db.commit()
    return removed
