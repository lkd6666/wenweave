"""Provider-normalised, durable text-to-image generation."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session, joinedload, object_session
from sqlalchemy.orm.exc import UnmappedInstanceError

from app.core.crypto import decrypt_secret
from app.db.session import SessionLocal
from app.models.ai_image_model import AIImageModel
from app.models.image_generation import (
    GeneratedImageAsset,
    ImageGeneration,
    ImageGenerationOperation,
    ImageGenerationPurpose,
    ImageGenerationSource,
    ImageGenerationStatus,
    ImageLibraryAsset,
)
from app.services import local_uploads
from app.services import oss_client
from app.services.document_images import (
    DocumentImageStorageError,
    StoredDocumentImage,
    delete_tracked_document_image,
    store_tracked_document_image,
)
from app.services.external_fetch import PublicFetchError, fetch_public_image
from app.models.storage_config import StorageConfig


DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS = 180
MIN_IMAGE_GENERATION_TIMEOUT_SECONDS = 30
MAX_IMAGE_GENERATION_TIMEOUT_SECONDS = 1800
POLL_INTERVAL_SECONDS = 1.5
UNUSED_ASSET_TTL = timedelta(days=7)
_DASHSCOPE_RESULT_HOST_RE = re.compile(
    r"^(?:dashscope-result-[a-z0-9-]+\.oss-cn-[a-z0-9-]+\.aliyuncs\.com|"
    r"dashscope-[a-z0-9-]+\.oss-accelerate\.aliyuncs\.com)$"
)


class ImageGenerationError(ValueError):
    pass


def _clamp_generation_timeout_seconds(value: int | None) -> int:
    value = int(value or DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS)
    return max(MIN_IMAGE_GENERATION_TIMEOUT_SECONDS, min(value, MAX_IMAGE_GENERATION_TIMEOUT_SECONDS))


def _generation_timeout_seconds(generation: ImageGeneration) -> int:
    return _clamp_generation_timeout_seconds(getattr(generation, "timeout_seconds", None))


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


class _CurrentImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.add(source.strip())


def _current_image_sources(current_html: str) -> set[str]:
    parser = _CurrentImageSourceParser()
    try:
        parser.feed(current_html or "")
        parser.close()
    except Exception:  # noqa: BLE001 - malformed article HTML should not break listing.
        return set()
    return parser.sources


def image_target_fingerprint(current_html: str, image_index: int, source_url: str = "") -> str:
    """Hash one image tag's attributes for optimistic replacement checks."""
    tags = re.findall(r"<img\b[^>]*>", current_html or "", flags=re.IGNORECASE)
    if image_index < 0 or image_index >= len(tags):
        return ""
    tag = tags[image_index]
    match = re.search(r"\bsrc\s*=\s*(['\"])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
    actual_source = match.group(2).strip() if match else ""
    # Browsers expose an HTML attribute as a decoded URL (`&`), while the
    # serialized document commonly stores the same value as `&amp;`. Compare
    # the canonical decoded values so signed image URLs are not rejected.
    if source_url and unescape(actual_source) != unescape(source_url.strip()):
        return ""
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def cover_source_fingerprint(source_url: str) -> str:
    """Return a stable optimistic-lock fingerprint for document cover metadata.

    Covers live outside article HTML, so an image-tag fingerprint cannot express
    whether the source that an edit candidate was made from is still current.
    Decode HTML entities to keep equivalent signed URLs stable across serializers.
    """
    normalized = unescape(str(source_url or "").strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def image_source_at(current_html: str, image_index: int) -> str:
    """Return the serialized src of one image for an Agent replacement."""
    tags = re.findall(r"<img\b[^>]*>", current_html or "", flags=re.IGNORECASE)
    if image_index < 0 or image_index >= len(tags):
        return ""
    match = re.search(r"\bsrc\s*=\s*(['\"])(.*?)\1", tags[image_index], flags=re.IGNORECASE | re.DOTALL)
    return unescape(match.group(2).strip()) if match else ""


def replace_image_source(current_html: str, image_index: int, source_url: str, next_url: str) -> str:
    """Replace exactly one img src while leaving all surrounding markup intact."""
    tags = list(re.finditer(r"<img\b[^>]*>", current_html or "", flags=re.IGNORECASE))
    if image_index < 0 or image_index >= len(tags):
        raise ImageGenerationError("目标图片不存在，请重新选择")
    tag_match = tags[image_index]
    tag = tag_match.group(0)
    src_match = re.search(r"(\bsrc\s*=\s*)(['\"])(.*?)\2", tag, flags=re.IGNORECASE | re.DOTALL)
    if not src_match or unescape(src_match.group(3).strip()) != unescape(source_url.strip()):
        raise ImageGenerationError("目标图片已发生变化，请重新选择")
    replacement = f"{src_match.group(1)}{src_match.group(2)}{html_escape_url(next_url)}{src_match.group(2)}"
    next_tag = tag[:src_match.start()] + replacement + tag[src_match.end():]
    return current_html[:tag_match.start()] + next_tag + current_html[tag_match.end():]


_STALE_TRANSFORMED_IMAGE_ATTRIBUTES = re.compile(
    r"\s+(?:srcset|sizes|data-crop-source|data-crop-rect|data-crop-rotation|data-preview-upload-id)"
    r"\s*=\s*(?:['\"][^'\"]*['\"]|[^\s>]+)",
    re.IGNORECASE,
)


def replace_transformed_image_source(current_html: str, image_index: int, source_url: str, next_url: str) -> str:
    """Replace one image after baking new pixels and clear stale derivatives.

    A crop/rotation changes every pixel variant, so retaining ``srcset`` would
    let a browser choose the old uncropped asset. Crop provenance describes a
    different source at this point as well. Presentation attributes such as
    ``alt``, ``class``, dimensions and inline style intentionally remain.
    """
    tags = list(re.finditer(r"<img\b[^>]*>", current_html or "", flags=re.IGNORECASE))
    if image_index < 0 or image_index >= len(tags):
        raise ImageGenerationError("目标图片不存在，请重新选择")
    tag_match = tags[image_index]
    tag = tag_match.group(0)
    src_match = re.search(r"(\bsrc\s*=\s*)(['\"])(.*?)\2", tag, flags=re.IGNORECASE | re.DOTALL)
    if not src_match or unescape(src_match.group(3).strip()) != unescape(source_url.strip()):
        raise ImageGenerationError("目标图片已发生变化，请重新选择")
    replacement = f"{src_match.group(1)}{src_match.group(2)}{html_escape_url(next_url)}{src_match.group(2)}"
    next_tag = tag[:src_match.start()] + replacement + tag[src_match.end():]
    next_tag = _STALE_TRANSFORMED_IMAGE_ATTRIBUTES.sub("", next_tag)
    return current_html[:tag_match.start()] + next_tag + current_html[tag_match.end():]


def html_escape_url(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#x27;").replace("<", "&lt;").replace(">", "&gt;")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _openai_images_endpoint(base_url: str, operation: str) -> str:
    """Accept an OpenAI Images API root, resource path, or full endpoint.

    Administrators commonly paste the URL exposed by a gateway.  Depending on
    the provider UI it may be ``.../v1``, ``.../v1/images`` or an exact
    ``.../v1/images/generations`` endpoint.  Treating all of those as API
    roots previously duplicated the ``images`` segment for the latter two.
    """
    normalized_operation = "edits" if operation == "edit" else "generations"
    cleaned = base_url.strip().rstrip("/")
    lowered = cleaned.lower()
    for endpoint in ("generations", "edits"):
        suffix = f"/images/{endpoint}"
        if lowered.endswith(suffix):
            return f"{cleaned[:-len(suffix)]}/images/{normalized_operation}"
    if lowered.endswith("/images"):
        return f"{cleaned}/{normalized_operation}"
    return _normalise_url(cleaned, f"images/{normalized_operation}")


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
    """Extract a concise, user-readable detail from an HTTP error response."""
    request_url = str(exc.request.url)
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
                return f"HTTP {exc.response.status_code}: {str(msg)[:300]}（请求：{request_url}）"
    except Exception:  # noqa: BLE001
        pass
    text = exc.response.text[:300].strip()
    detail = f"HTTP {exc.response.status_code}" + (f": {text}" if text else "")
    return f"{detail}（请求：{request_url}）"


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


def _source_content_type(data: bytes) -> str:
    try:
        return local_uploads.inspect_image(data).content_type
    except local_uploads.LocalUploadError:
        return "image/png"


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
    source_data: bytes | None = None,
) -> ProviderGenerationResult:
    payload: dict[str, Any] = {
        "model": model.model_name,
        "prompt": generation.prompt,
        "n": generation.quantity,
        "size": _size_for(size_protocol, generation.aspect_ratio),
    }
    if send_quality and generation.quality and generation.quality != "auto":
        payload["quality"] = generation.quality
    if getattr(generation, "operation", ImageGenerationOperation.GENERATE) == ImageGenerationOperation.EDIT:
        if not source_data:
            raise ImageGenerationError("编辑任务缺少可读取的原图")
        source_content_type = _source_content_type(source_data)
        files = {"image": ("source-image", source_data, source_content_type)}
        form = {key: str(value) for key, value in payload.items()}
        response = await client.post(
            _openai_images_endpoint(base_url, "edit"),
            headers={"Authorization": f"Bearer {api_key}"},
            data=form,
            files=files,
        )
    else:
        response = await client.post(
            _openai_images_endpoint(base_url, "generate"),
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
    client: httpx.AsyncClient, base_url: str, api_key: str, model: AIImageModel, generation: ImageGeneration,
    *, source_data: bytes | None = None,
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
    source_data_uri = (
        f"data:{_source_content_type(source_data)};base64,{base64.b64encode(source_data).decode('ascii')}"
        if getattr(generation, "operation", ImageGenerationOperation.GENERATE) == ImageGenerationOperation.EDIT and source_data
        else ""
    )
    if is_wan27:
        endpoint = _normalise_url(api_base, "services/aigc/image-generation/generation")
        payload: dict[str, Any] = {
            "model": model.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": ([{"image": source_data_uri}] if source_data_uri else []) + [{"text": generation.prompt}],
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
            "input": {"prompt": generation.prompt, **({"image": source_data_uri} if source_data_uri else {})},
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
    poll_attempts = max(1, int(_generation_timeout_seconds(generation) / max(POLL_INTERVAL_SECONDS, 0.01)) + 1)
    for _ in range(poll_attempts):
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
    client: httpx.AsyncClient, base_url: str, api_key: str, model: AIImageModel, generation: ImageGeneration,
    *, source_data: bytes | None = None,
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
    if getattr(generation, "operation", ImageGenerationOperation.GENERATE) == ImageGenerationOperation.EDIT:
        if not source_data:
            raise ImageGenerationError("编辑任务缺少可读取的原图")
        source_content_type = _source_content_type(source_data)
        response = await client.post(
            _openai_images_endpoint(base_url, "edit"),
            headers={"Authorization": f"Bearer {api_key}"},
            data={key: str(value) for key, value in payload.items() if key != "response_format"},
            files={"image": ("source-image", source_data, source_content_type)},
        )
    else:
        response = await client.post(
            _openai_images_endpoint(base_url, "generate"),
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


async def _call_provider_once(model: AIImageModel, generation: ImageGeneration, source_data: bytes | None = None) -> ProviderGenerationResult:
    provider = model.provider
    protocol = str(provider.image_protocol or "")
    base_url = str(provider.image_base_url or "").strip()
    if not protocol or not base_url:
        raise ImageGenerationError("该 Provider 尚未配置图片生成端点")
    api_key = decrypt_secret(provider.api_key_encrypted)
    timeout_seconds = float(_generation_timeout_seconds(generation))
    timeout = httpx.Timeout(timeout_seconds, connect=min(20.0, timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        if protocol == "openai_images":
            return await _openai_images(client, base_url, api_key, model, generation, source_data=source_data)
        if protocol == "dashscope_images":
            return await _dashscope_images(client, base_url, api_key, model, generation, source_data=source_data)
        if protocol == "volcengine_ark_images":
            return await _volcengine_ark_images(client, base_url, api_key, model, generation, source_data=source_data)
    raise ImageGenerationError("不支持的图片生成协议")


def _merge_usage(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Accumulate numeric usage across retries while preserving other fields."""
    for key, value in source.items():
        if isinstance(value, (int, float)) and isinstance(target.get(key), (int, float)):
            target[key] += value
        elif key not in target:
            target[key] = value


async def _call_provider(model: AIImageModel, generation: ImageGeneration, source_data: bytes | None = None) -> ProviderGenerationResult:
    """Return the requested number of images even when a provider returns fewer.

    Some native DashScope image endpoints accept ``n`` but still emit one image
    per task. Repeating the normalized request fills the user's requested
    quantity while keeping the OpenAI/Ark fast path single-call when they
    already return all requested images.
    """
    requested = max(1, min(int(generation.quantity), 4))
    images: list[ProviderImage] = []
    seen_images: set[str] = set()
    usage: dict[str, Any] = {}
    task_ids: list[str] = []
    last_error: ImageGenerationError | None = None
    for _ in range(requested):
        try:
            result = await _call_provider_once(model, generation, source_data)
        except ImageGenerationError as exc:
            last_error = exc
            if not images:
                raise
            break
        # A few gateways have been observed to repeat the same URL (or the
        # same base64 payload) for every item in an ``n`` response. Persisting
        # those entries would make a batch look like several different images
        # while actually rendering one image repeatedly. Keep only unique
        # provider results; the bounded retry loop still gives providers that
        # return fewer images a chance to fill the requested quantity.
        for image in result.images:
            identity = ""
            if image.url:
                parsed_url = urlsplit(image.url.strip())
                identity = (
                    f"{parsed_url.scheme.lower()}://{parsed_url.netloc.lower()}{parsed_url.path}"
                    if parsed_url.scheme and parsed_url.netloc
                    else image.url.strip()
                )
            if not identity and image.data:
                identity = hashlib.sha256(image.data).hexdigest()
            if identity and identity in seen_images:
                continue
            if identity:
                seen_images.add(identity)
            images.append(image)
        _merge_usage(usage, result.usage)
        if result.provider_task_id:
            task_ids.append(result.provider_task_id)
        if len(images) >= requested:
            break
    if not images:
        raise last_error or ImageGenerationError("图片模型未返回可用图片")
    return ProviderGenerationResult(
        images=tuple(images[:requested]),
        usage=usage,
        provider_task_id=",".join(task_ids),
    )


async def _call_provider_with_timeout(
    model: AIImageModel,
    generation: ImageGeneration,
    source_data: bytes | None = None,
) -> ProviderGenerationResult:
    timeout_seconds = _generation_timeout_seconds(generation)
    try:
        async with asyncio.timeout(timeout_seconds):
            return await _call_provider(model, generation, source_data)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ImageGenerationError(f"图片生成超过指定的 {timeout_seconds} 秒") from exc


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


async def materialize_source_image(source: str, *, storage: StorageConfig | None = None) -> tuple[bytes, str]:
    """Read an article image from a local capability URL, data URI, or HTTPS URL."""
    value = str(source or "").strip()
    if not value:
        raise ImageGenerationError("编辑任务缺少原图")
    if value.lower().startswith("data:image/"):
        try:
            header, encoded = value.split(",", 1)
            if ";base64" not in header.lower():
                raise ValueError("图片不是 Base64 data URI")
            data = base64.b64decode(encoded, validate=True)
            info = local_uploads.inspect_image(data)
            return data, info.content_type
        except (ValueError, binascii.Error, local_uploads.LocalUploadError) as exc:
            raise ImageGenerationError("文章内联图片无效") from exc
    if value.startswith("/api/documents/local-images/"):
        name = value.rsplit("/", 1)[-1].split("?", 1)[0]
        path = local_uploads.local_path(f"local/images/{name}")
        try:
            data = path.read_bytes()
            info = local_uploads.inspect_image(data)
            return data, info.content_type
        except (OSError, local_uploads.LocalUploadError) as exc:
            raise ImageGenerationError("无法读取文章原图") from exc
    if storage is not None:
        object_key = oss_client.storage_object_key_for_url(storage, value)
        if object_key:
            try:
                data = oss_client.get_object_bytes(storage, object_key)
                info = local_uploads.inspect_image(data)
                return data, info.content_type
            except (oss_client.OSSNotConfiguredError, oss_client.ObjectStorageError, ValueError, OSError) as exc:
                raise ImageGenerationError("无法读取文章原图：对象存储中的图片不可用") from exc
    try:
        timeout = httpx.Timeout(30, connect=10)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            data, info = await fetch_public_image(client, value, trusted_proxy_hosts=_trusted_provider_image_hosts(value))
            return data, info.content_type
    except (PublicFetchError, httpx.HTTPError) as exc:
        raise ImageGenerationError(f"无法读取文章原图：{exc}") from exc


def asset_is_currently_applied(asset_url: str, current_html: str = "", cover_url: str = "") -> bool:
    """Whether an asset is still referenced by the document's current state.

    ``is_applied`` is intentionally sticky because past document versions may
    still need the stored object. Candidate controls, however, must follow the
    live article rather than that historical retention marker.
    """
    url = str(asset_url or "").strip()
    if not url:
        return False
    return url == str(cover_url or "").strip() or url in _current_image_sources(current_html)


def generation_payload(
    generation: ImageGeneration,
    *,
    current_html: str = "",
    cover_url: str = "",
) -> dict[str, Any]:
    try:
        usage = json.loads(generation.usage_json or "{}")
    except json.JSONDecodeError:
        usage = {}
    assets = list(generation.assets)
    library_assets: dict[str, ImageLibraryAsset] = {}
    try:
        db = object_session(generation)
    except UnmappedInstanceError:
        db = None
    if db is not None and assets:
        generated_ids = [asset.id for asset in assets]
        rows = (
            db.query(ImageLibraryAsset)
            .filter(
                ImageLibraryAsset.generated_asset_id.in_(generated_ids),
                ImageLibraryAsset.deleted_at.is_(None),
            )
            .all()
        )
        library_assets = {row.generated_asset_id: row for row in rows}

    def generated_asset_payload(asset: GeneratedImageAsset) -> dict[str, Any]:
        library_asset = library_assets.get(asset.id)
        library_url = ""
        if library_asset is not None and db is not None:
            from app.services.image_library import refreshed_asset_url

            library_url = refreshed_asset_url(db, library_asset)
        return {
            "id": asset.id,
            "generation_id": asset.generation_id,
            "url": asset.url,
            "content_type": asset.content_type,
            "size": asset.size,
            "width": asset.width,
            "height": asset.height,
            "revised_prompt": asset.revised_prompt,
            "library_asset_id": library_asset.id if library_asset is not None else "",
            "library_url": library_url,
            "is_applied": asset.is_applied,
            "is_currently_applied": asset_is_currently_applied(asset.url, current_html, cover_url),
            "applied_at": asset.applied_at.isoformat() if asset.applied_at else None,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        }

    return {
        "id": generation.id,
        "document_id": generation.document_id,
        "session_id": generation.session_id,
        "model_id": generation.model_id,
        "source": generation.source.value,
        "purpose": generation.purpose.value,
        "operation": generation.operation.value,
        "prompt": generation.prompt,
        "quantity": generation.quantity,
        "aspect_ratio": generation.aspect_ratio,
        "quality": generation.quality,
        "timeout_seconds": _generation_timeout_seconds(generation),
        "anchor_block_id": generation.anchor_block_id,
        "source_image_url": generation.source_image_url,
        "source_image_hash": generation.source_image_hash,
        "source_asset_url": generation.source_asset_url,
        "target_image_index": generation.target_image_index,
        "direct_insert": generation.direct_insert,
        "status": generation.status.value,
        "error_message": generation.error_message,
        "usage": usage if isinstance(usage, dict) else {},
        "created_at": generation.created_at.isoformat() if generation.created_at else None,
        "updated_at": generation.updated_at.isoformat() if generation.updated_at else None,
        "finished_at": generation.finished_at.isoformat() if generation.finished_at else None,
        "assets": [generated_asset_payload(asset) for asset in assets],
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
    timeout_seconds: int = DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS,
    anchor_block_id: str = "",
    direct_insert: bool = False,
    operation: ImageGenerationOperation = ImageGenerationOperation.GENERATE,
    source_image_url: str = "",
    source_image_hash: str = "",
    source_asset_url: str = "",
    source_object_key: str = "",
    source_storage_mode: str = "",
    target_image_index: int = -1,
) -> ImageGeneration:
    generation = ImageGeneration(
        id=str(uuid4()),
        document_id=document_id,
        session_id=session_id,
        model_id=model_id,
        user_id=user_id,
        source=source,
        purpose=purpose,
        operation=operation,
        prompt=prompt,
        quantity=quantity,
        aspect_ratio=aspect_ratio,
        quality=quality,
        timeout_seconds=_clamp_generation_timeout_seconds(timeout_seconds),
        anchor_block_id=anchor_block_id,
        source_image_url=source_image_url,
        source_image_hash=source_image_hash,
        source_asset_url=source_asset_url,
        source_object_key=source_object_key,
        source_storage_mode=source_storage_mode,
        target_image_index=target_image_index,
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
        source_data = None
        source_content_type = ""
        if getattr(generation, "operation", ImageGenerationOperation.GENERATE) == ImageGenerationOperation.EDIT:
            storage = db.query(StorageConfig).first()
            source_data, source_content_type = await materialize_source_image(
                generation.source_asset_url or generation.source_image_url,
                storage=storage,
            )
        result = await _call_provider_with_timeout(generation.model, generation, source_data)
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
            generated_asset = GeneratedImageAsset(
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
            db.add(generated_asset)
            from app.services.image_library import ensure_generated_asset_in_library

            ensure_generated_asset_in_library(db, generation, generated_asset)
            created_asset_count += 1
        if generation.cancel_requested:
            generation.status = ImageGenerationStatus.CANCELLED
        elif created_asset_count == 0:
            raise ImageGenerationError("图片生成没有产生可保存的结果")
        else:
            generation.status = ImageGenerationStatus.SUCCEEDED
            generation.error_message = ""
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
    removed = 0
    # Generated candidates are durable history and may also be referenced by
    # document versions after their library row is soft-deleted. Only the
    # temporary source copy used for AI editing is eligible for TTL cleanup.
    source_generations = (
        db.query(ImageGeneration)
        .filter(
            ImageGeneration.source_object_key != "",
            ImageGeneration.created_at < cutoff,
        )
        .all()
    )
    for generation in source_generations:
        delete_tracked_document_image(
            db,
            StoredDocumentImage(
                url=generation.source_asset_url,
                object_key=generation.source_object_key,
                storage_mode=generation.source_storage_mode,
            ),
        )
        generation.source_asset_url = ""
        generation.source_object_key = ""
        generation.source_storage_mode = ""
        removed += 1
    if removed:
        db.commit()
    return removed
