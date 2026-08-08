"""Shared reusable article-component templates and their durable image assets."""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup, Comment
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.models.storage_config import StorageConfig
from app.models.template_library import (
    TemplateCategory,
    TemplateGeneration,
    TemplateGenerationStatus,
    TemplateImageAsset,
    TemplateLibraryItem,
    TemplateSourceType,
)
from app.services import local_uploads, oss_client
from app.services.external_fetch import PublicFetchError, fetch_public_image
from app.services.image_localization import ImageLocalizationError, StoredImage, localize_html_images


MAX_TEMPLATE_HTML_CHARS = 400_000
MAX_TEMPLATE_IMAGES = 30
MAX_TEMPLATE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEMPLATE_IMAGE_TOTAL_BYTES = 50 * 1024 * 1024
REMOTE_TIMEOUT_SECONDS = 10.0
REMOTE_MAX_REDIRECTS = 3
REMOTE_FETCH_CONCURRENCY = 3
ASSET_URL_PREFIX = "/api/template-library/assets/"
_CODE_FENCE = re.compile(r"^\s*```(?:html)?\s*|\s*```\s*$", re.IGNORECASE)
_DANGEROUS_URL = re.compile(r"^\s*(?:javascript|vbscript|file):", re.IGNORECASE)
_DANGEROUS_STYLE = re.compile(
    r"(?:expression\s*\(|@import\b|behavior\s*:|url\s*\(\s*['\"]?\s*(?:javascript|vbscript|file)\s*:)",
    re.IGNORECASE,
)
_DATA_IMAGE = re.compile(r"^data:([a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)
_ALLOWED_TAGS = {
    "article", "section", "div", "p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s",
    "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "br", "hr", "pre", "code",
    "figure", "figcaption", "small", "sup", "sub", "a", "img",
}
_DROP_TAGS = {"script", "style", "link", "iframe", "object", "embed", "form", "input", "button", "textarea", "select", "video", "audio", "canvas", "svg", "math"}
_VOID_TAGS = {"br", "hr", "img"}


class TemplateLibraryError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateImageLocalization:
    html: str
    localized_count: int
    stored_images: tuple[StoredImage, ...]


@dataclass(frozen=True)
class TemplateAssetStorageObject:
    object_key: str
    storage_mode: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def asset_url(asset_id: str) -> str:
    return f"{ASSET_URL_PREFIX}{asset_id}"


def _storage_if_configured(db: Session) -> StorageConfig | None:
    storage = db.query(StorageConfig).first()
    if not storage or not storage.endpoint or not storage.access_key_id or not storage.access_key_secret_encrypted or not storage.bucket:
        return None
    return storage


def _normalise_https_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise TemplateLibraryError("图片链接格式无效") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise TemplateLibraryError("外链图片仅支持公开 HTTPS 地址")
    if parsed.port not in {None, 443}:
        raise TemplateLibraryError("外链图片仅支持标准 HTTPS 端口")
    return parsed.geturl()


async def _ensure_public_host(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise TemplateLibraryError("图片链接域名无效")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise TemplateLibraryError("不允许访问本机或内网图片地址")
        return
    try:
        records = await asyncio.get_running_loop().getaddrinfo(host, parsed.port or 443, type=0)
    except OSError as exc:
        raise TemplateLibraryError("无法解析图片链接域名") from exc
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise TemplateLibraryError("无法解析图片链接域名")
    for address in addresses:
        try:
            if not ipaddress.ip_address(address).is_global:
                raise TemplateLibraryError("图片链接指向了不允许访问的网络地址")
        except ValueError as exc:
            raise TemplateLibraryError("图片链接解析结果无效") from exc


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


async def _fetch_remote_image(client: httpx.AsyncClient, source: str) -> tuple[bytes, local_uploads.ImageInfo]:
    try:
        return await fetch_public_image(client, source)
    except PublicFetchError as exc:
        raise TemplateLibraryError(str(exc)) from exc


def _decode_data_image(source: str) -> tuple[bytes, local_uploads.ImageInfo]:
    match = _DATA_IMAGE.fullmatch(source.strip())
    if not match:
        raise TemplateLibraryError("内嵌图片格式无效")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise TemplateLibraryError("内嵌图片编码无效") from exc
    if len(data) > MAX_TEMPLATE_IMAGE_BYTES:
        raise TemplateLibraryError("内嵌图片超过 10MB 限制")
    try:
        return data, local_uploads.inspect_image(data)
    except local_uploads.LocalUploadError as exc:
        raise TemplateLibraryError(str(exc)) from exc


def _store_asset(db: Session, template_id: int, data: bytes, image: local_uploads.ImageInfo, original_url: str) -> TemplateImageAsset:
    asset_id = str(uuid4())
    storage = _storage_if_configured(db)
    if storage is None:
        storage_mode = "local"
        object_key = f"local/template-library/{asset_id}.{image.extension}"
        local_uploads.save_bytes(object_key, data, lambda path: local_uploads.validate_image(path, image.content_type))
    else:
        storage_mode = "oss"
        object_key = f"yibanpaiban/template-library/{asset_id}.{image.extension}"
        try:
            oss_client.put_object_bytes(storage, object_key, data, image.content_type)
        except Exception as exc:  # noqa: BLE001
            raise TemplateLibraryError("模板图片保存失败") from exc
    asset = TemplateImageAsset(
        id=asset_id,
        template_id=template_id,
        original_url=original_url[:2048],
        object_key=object_key,
        storage_mode=storage_mode,
        content_type=image.content_type,
        size=len(data),
    )
    db.add(asset)
    return asset


def delete_asset_object(db: Session, asset: TemplateImageAsset) -> None:
    delete_asset_storage_object(db, TemplateAssetStorageObject(object_key=asset.object_key, storage_mode=asset.storage_mode))


def delete_asset_storage_object(db: Session, asset: TemplateAssetStorageObject) -> None:
    try:
        if asset.storage_mode == "local":
            local_uploads.delete(asset.object_key)
            return
        storage = _storage_if_configured(db)
        if storage is not None:
            oss_client.delete_object(storage, asset.object_key)
    except Exception:
        # DB deletion still makes the URL unusable; a later storage lifecycle
        # cleanup can collect an unreachable object if the provider is down.
        return


def delete_asset_storage_objects(db: Session, assets: tuple[TemplateAssetStorageObject, ...]) -> None:
    for asset in assets:
        delete_asset_storage_object(db, asset)


def read_asset_bytes(db: Session, asset: TemplateImageAsset) -> bytes:
    try:
        if asset.storage_mode == "local":
            return local_uploads.local_path(asset.object_key).read_bytes()
        storage = _storage_if_configured(db)
        if storage is None:
            raise TemplateLibraryError("模板图片存储不可用")
        return oss_client.get_object_bytes(storage, asset.object_key)
    except (OSError, local_uploads.LocalUploadError) as exc:
        raise TemplateLibraryError("模板图片不存在") from exc
    except TemplateLibraryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TemplateLibraryError("模板图片不存在") from exc


def _normalise_html(raw_html: str) -> BeautifulSoup:
    if len(raw_html) > MAX_TEMPLATE_HTML_CHARS:
        raise TemplateLibraryError("模板源码过长")
    soup = BeautifulSoup(raw_html, "html.parser")
    for comment in soup.find_all(string=lambda item: isinstance(item, Comment)):
        comment.extract()
    for tag in list(soup.find_all(True)):
        name = (tag.name or "").lower()
        if name in _DROP_TAGS:
            tag.decompose()
            continue
        if name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue
        for attr, value in list(tag.attrs.items()):
            lower = attr.lower()
            rendered = " ".join(value) if isinstance(value, list) else str(value)
            if lower.startswith("on") or (lower == "style" and _DANGEROUS_STYLE.search(rendered)):
                del tag.attrs[attr]
                continue
            if lower not in {"style", "href", "src", "srcset", "alt", "title", "target", "rel", "referrerpolicy", "width", "height", "colspan", "rowspan", "align", "valign", "leaf", "data-crop-source", "data-crop-rect"}:
                del tag.attrs[attr]
                continue
            if lower in {"href", "src"} and _DANGEROUS_URL.match(rendered):
                del tag.attrs[attr]
        if name == "a":
            href = str(tag.get("href") or "").strip()
            if href and not (href.startswith("https://") or href.startswith("http://") or href.startswith("mailto:") or href.startswith("#")):
                tag.attrs.pop("href", None)
            if tag.get("target") == "_blank":
                tag["rel"] = "noopener noreferrer"
    return soup


def _html_fragment(soup: BeautifulSoup) -> str:
    return "".join(str(node) for node in soup.contents).strip()


def _template_asset_id(source: str) -> str | None:
    path = urlsplit(source).path if source.lower().startswith(("http://", "https://")) else source
    match = re.fullmatch(re.escape(ASSET_URL_PREFIX) + r"([0-9a-fA-F-]{36})", path)
    return match.group(1) if match else None


async def localize_template_html(db: Session, template: TemplateLibraryItem, raw_html: str) -> TemplateImageLocalization:
    soup = _normalise_html(raw_html)
    normalized_html = _html_fragment(soup)
    if not normalized_html:
        raise TemplateLibraryError("模板不包含可用内容")

    def is_existing_own_asset(source: str) -> bool:
        asset_id = _template_asset_id(source)
        if not asset_id:
            return False
        asset = db.get(TemplateImageAsset, asset_id)
        return bool(asset and asset.template_id == template.id)

    async def load_image(source: str, client: httpx.AsyncClient):
        asset_id = _template_asset_id(source)
        if asset_id:
            asset = db.get(TemplateImageAsset, asset_id)
            if asset is None:
                raise ImageLocalizationError("模板图片不存在")
            try:
                data = read_asset_bytes(db, asset)
                return data, local_uploads.inspect_image(data)
            except (TemplateLibraryError, local_uploads.LocalUploadError) as exc:
                raise ImageLocalizationError(str(exc) or "模板图片不存在") from exc
        try:
            return await fetch_public_image(client, source)
        except PublicFetchError as exc:
            raise ImageLocalizationError(str(exc)) from exc

    def store_image(data: bytes, image: local_uploads.ImageInfo, source: str) -> StoredImage:
        asset = _store_asset(db, template.id, data, image, source)
        return StoredImage(url=asset_url(asset.id), handle=asset)

    def cleanup_image(persisted: StoredImage) -> None:
        if isinstance(persisted.handle, TemplateImageAsset):
            delete_asset_object(db, persisted.handle)
            db.delete(persisted.handle)

    try:
        result = await localize_html_images(
            normalized_html,
            load_image=load_image,
            store_image=store_image,
            cleanup_image=cleanup_image,
            is_local_source=is_existing_own_asset,
            max_images=MAX_TEMPLATE_IMAGES,
            max_total_bytes=MAX_TEMPLATE_IMAGE_TOTAL_BYTES,
            fetch_concurrency=REMOTE_FETCH_CONCURRENCY,
        )
    except ImageLocalizationError as exc:
        raise TemplateLibraryError(str(exc)) from exc
    return TemplateImageLocalization(
        html=result.html,
        localized_count=result.localized_count,
        stored_images=result.stored_images,
    )


def cleanup_template_localization(db: Session, result: TemplateImageLocalization) -> None:
    for persisted in reversed(result.stored_images):
        if isinstance(persisted.handle, TemplateImageAsset):
            delete_asset_object(db, persisted.handle)
            db.delete(persisted.handle)


def referenced_asset_ids(html: str) -> set[str]:
    return set(re.findall(re.escape(ASSET_URL_PREFIX) + r"([0-9a-fA-F-]{36})", html))


def remove_unreferenced_assets(
    db: Session,
    template: TemplateLibraryItem,
    html: str,
    *,
    cleanup_objects: bool = True,
) -> tuple[TemplateAssetStorageObject, ...]:
    kept = referenced_asset_ids(html)
    assets = db.query(TemplateImageAsset).filter(TemplateImageAsset.template_id == template.id).all()
    removed: list[TemplateAssetStorageObject] = []
    for asset in assets:
        if asset.id not in kept:
            removed.append(TemplateAssetStorageObject(object_key=asset.object_key, storage_mode=asset.storage_mode))
            if cleanup_objects:
                delete_asset_object(db, asset)
            db.delete(asset)
    return tuple(removed)


def category_or_error(db: Session, category_id: int | None) -> TemplateCategory | None:
    if category_id is None:
        return None
    category = db.get(TemplateCategory, category_id)
    if category is None:
        raise TemplateLibraryError("模板分类不存在")
    return category


def warning_payload(value: str) -> list[dict[str, str]]:
    try:
        warnings = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [
        {"source": str(item.get("source") or ""), "message": str(item.get("message") or "图片转存失败")}
        for item in warnings if isinstance(item, dict)
    ]


def template_payload(template: TemplateLibraryItem) -> dict:
    return {
        "id": template.id,
        "name": template.name,
        "category_id": template.category_id,
        "html": template.html,
        "source_type": template.source_type.value if isinstance(template.source_type, TemplateSourceType) else str(template.source_type),
        "image_warnings": warning_payload(template.image_warnings_json),
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def generation_payload(generation: TemplateGeneration) -> dict:
    return {
        "id": generation.id,
        "status": generation.status.value if isinstance(generation.status, TemplateGenerationStatus) else str(generation.status),
        "prompt": generation.prompt,
        "output_html": generation.output_html,
        "error_message": generation.error_message,
        "created_at": generation.created_at,
        "finished_at": generation.finished_at,
    }


def _strip_code_fence(value: str) -> str:
    return _CODE_FENCE.sub("", value).strip()


def _generation_prompt(prompt: str) -> str:
    return f"""你是微信公众号图文排版组件设计器。依据用户需求生成一个可直接插入文章的静态 HTML 组件，不是完整文章。

用户需求：{prompt}

仅输出 HTML 片段，不要 Markdown 代码围栏或解释。只使用 section、div、p、span、h1-h6、strong、em、ul、ol、li、blockquote、table、a、img 等静态标签；所有视觉样式必须写在元素内 style。不要使用 script、style、class、id、SVG、表单、iframe、外部字体、动画或外部图片。为可替换的文字使用有意义的中文占位内容。"""


async def _ask_generation_model(generation: TemplateGeneration) -> str:
    from app.services.chat_agent import build_chat_model
    from app.models.model_call_record import ModelCallSource
    from app.services.model_call_accounting import invoke_with_accounting

    db = SessionLocal()
    try:
        model = db.get(AIModel, generation.model_id)
        if model is None:
            raise TemplateLibraryError("所选 AI 模型不存在")
        chat_model, _ = build_chat_model(model.provider, model, "disabled", max_retries=0, request_timeout_seconds=90, streaming=False)
        response = await invoke_with_accounting(
            asyncio.wait_for(
                chat_model.ainvoke([
                    SystemMessage(content="只生成安全、静态的公众号 HTML 组件。"),
                    HumanMessage(content=_generation_prompt(generation.prompt)),
                ]),
                timeout=100,
            ),
            model_id=model.id,
            user_id=generation.user_id,
            source=ModelCallSource.TEMPLATE_GENERATION,
            source_id=generation.id,
        )
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        return _strip_code_fence(str(content))
    finally:
        db.close()


async def run_generation(generation_id: str) -> None:
    db = SessionLocal()
    try:
        generation = db.get(TemplateGeneration, generation_id)
        if generation is None or generation.status != TemplateGenerationStatus.PENDING:
            return
        if generation.cancel_requested:
            generation.status = TemplateGenerationStatus.CANCELLED
            generation.finished_at = _utcnow()
            db.commit()
            return
        generation.status = TemplateGenerationStatus.RUNNING
        db.commit()
        html = await _ask_generation_model(generation)
        soup = _normalise_html(html)
        output_html = _html_fragment(soup)
        if not output_html:
            raise TemplateLibraryError("AI 没有生成可用模板")
        db.refresh(generation)
        if generation.cancel_requested:
            generation.status = TemplateGenerationStatus.CANCELLED
        else:
            generation.output_html = output_html
            generation.status = TemplateGenerationStatus.SUCCEEDED
        generation.finished_at = _utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        generation = db.get(TemplateGeneration, generation_id)
        if generation is not None:
            generation.status = TemplateGenerationStatus.FAILED
            generation.error_message = str(exc)[:2048] or "模板生成失败"
            generation.finished_at = _utcnow()
            db.commit()
    finally:
        db.close()


def start_generation(generation_id: str) -> asyncio.Task[None]:
    return asyncio.create_task(run_generation(generation_id))
