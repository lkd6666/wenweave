"""Server-side integration with WeChat Official Account draft APIs."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
import socket
import time
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html import unescape
from io import BytesIO
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.crypto import decrypt_secret
from app.models.wechat_account import WeChatAccount
from app.schemas.wechat import WeChatArticleMetadata
from app.services.agent_run_manager import WORKER_ID
from app.services.html_validation import validate_html_structure
from app.services.image_localization import css_url_sources, replace_css_urls, replace_srcset_sources, srcset_source_spans
from app.services.runtime_diagnostics import log_process_memory


WECHAT_API_BASE = "https://api.weixin.qq.com"
TOKEN_REFRESH_MARGIN_SECONDS = 300
PERMANENT_IMAGE_LIMIT = 10 * 1024 * 1024
BODY_IMAGE_LIMIT = PERMANENT_IMAGE_LIMIT
TEMPORARY_BODY_IMAGE_LIMIT = 1 * 1024 * 1024
COVER_IMAGE_LIMIT = PERMANENT_IMAGE_LIMIT
MAX_REDIRECTS = 3
IMAGE_MEMORY_BUFFER_LIMIT = 1 * 1024 * 1024
TOKEN_ERROR_CODES = {40001, 40014, 42001}
BODY_IMAGE_CACHE_RETRY_ERROR_CODES = {40007, 40008, 47001}
TRUSTED_OSS_BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")
# WeChat generates a digest from the article content when this field is empty.
# A zero-width space is accepted as a text value but remains visually blank in
# the draft editor, allowing an intentionally empty digest to stay empty.
WECHAT_EMPTY_DIGEST_PLACEHOLDER = "\u200b"
COVER_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp"}
BODY_IMAGE_TYPES = COVER_IMAGE_TYPES
BODY_IMAGE_SOURCE_TYPES = BODY_IMAGE_TYPES | {"image/webp"}
BODY_IMAGE_TRANSCODE_TYPES = {"image/webp"}
TEMPORARY_BODY_IMAGE_TYPES = {"image/jpeg", "image/png"}
MAX_BODY_IMAGE_PIXELS = 40_000_000
MAX_BODY_IMAGE_ANIMATION_FRAMES = 300
MAX_BODY_IMAGE_ANIMATION_PIXELS = 80_000_000
MAX_DRAFT_TARGETS = 100
DRAFT_TARGET_PAGE_SIZE = 20
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}
SENSITIVE_QUERY_VALUE_PATTERN = re.compile(
    r"([?&](?:access_token|app_secret|secret|api[_-]?key|signature|sign)=)[^&#\s]+",
    re.IGNORECASE,
)
SENSITIVE_FIELD_VALUE_PATTERN = re.compile(
    r"((?:[\"']?)(?:access_token|app_secret|secret|api[_-]?key|signature|sign)(?:[\"']?)\s*[=:]\s*(?:[\"']?))([^\s,}&\"']+)",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)


def _redact_sensitive_text(value: str) -> str:
    """Keep request failures useful without leaking credential values to logs or clients."""
    value = SENSITIVE_QUERY_VALUE_PATTERN.sub(r"\1[REDACTED]", value)
    return SENSITIVE_FIELD_VALUE_PATTERN.sub(r"\1[REDACTED]", value)


class ImagePayload:
    """A rewindable image body that spills to disk above one MiB."""

    def __init__(
        self,
        stream: BinaryIO,
        *,
        content_type: str,
        filename: str,
        size: int,
        content_sha256: str,
    ) -> None:
        self._stream = stream
        self.content_type = content_type
        self.filename = filename
        self.size = size
        self.content_sha256 = content_sha256

    @classmethod
    def from_bytes(cls, content: bytes, *, content_type: str, filename: str) -> "ImagePayload":
        stream = SpooledTemporaryFile(max_size=IMAGE_MEMORY_BUFFER_LIMIT, mode="w+b")
        try:
            stream.write(content)
            stream.seek(0)
            return cls(
                stream,
                content_type=content_type,
                filename=filename,
                size=len(content),
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
        except BaseException:
            stream.close()
            raise

    @property
    def is_file_backed(self) -> bool:
        return bool(getattr(self._stream, "_rolled", False))

    def rewind(self) -> BinaryIO:
        self._stream.seek(0)
        return self._stream

    def read_bytes(self) -> bytes:
        stream = self.rewind()
        return stream.read()

    def close(self) -> None:
        self._stream.close()


class WeChatApiError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class CoverImage:
    """Publicly compatible cover wrapper backed by a rewindable image stream."""

    def __init__(self, content: bytes | ImagePayload, content_type: str, filename: str) -> None:
        self._payload = (
            content
            if isinstance(content, ImagePayload)
            else ImagePayload.from_bytes(content, content_type=content_type, filename=filename)
        )
        self.content_type = content_type
        self.filename = filename

    @property
    def content(self) -> bytes:
        """Compatibility accessor; the upload path uses ``payload`` to avoid a copy."""
        return self._payload.read_bytes()

    @property
    def payload(self) -> ImagePayload:
        return self._payload

    @property
    def content_sha256(self) -> str:
        return self._payload.content_sha256

    def close(self) -> None:
        self._payload.close()


@dataclass(frozen=True)
class PermanentImage:
    media_id: str
    url: str


@dataclass(frozen=True)
class BodyImageCacheEntry:
    source_url_sha256: str
    content_sha256: str
    content_type: str
    wechat_url: str
    upload_mode: str


@dataclass(frozen=True)
class BodyImageReplacementResult:
    html: str
    cache_entries: tuple[BodyImageCacheEntry, ...]
    cached_source_hashes: frozenset[str]


@dataclass(frozen=True)
class DraftPushResult:
    media_id: str
    cover_media_id: str
    cover_media_was_uploaded: bool
    body_image_cache_entries: tuple[BodyImageCacheEntry, ...] = ()
    created_new_draft: bool = False


@dataclass(frozen=True)
class DraftTarget:
    media_id: str
    title: str
    update_time: int | None
    article_count: int


ProgressCallback = Callable[[str, int, str], Awaitable[None]]
LocalImageLoader = Callable[[str], tuple[bytes, str, str] | ImagePayload | None]


class WeChatOfficialAccountClient:
    """Small request client that keeps credentials and access tokens server-side."""

    _token_cache: dict[int, tuple[str, float]] = {}
    _cache_lock = asyncio.Lock()

    @classmethod
    async def clear_token_cache(cls) -> None:
        async with cls._cache_lock:
            cls._token_cache.clear()

    async def test_account(self, account: WeChatAccount) -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=False) as client:
            await self._access_token(client, account)

    async def download_cover(
        self, source_url: str, *, trusted_image_hosts: set[str] | None = None
    ) -> CoverImage:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
            payload = await self._download_image(
                client,
                source_url,
                allowed_types=COVER_IMAGE_TYPES,
                max_bytes=COVER_IMAGE_LIMIT,
                label="封面",
                trusted_image_hosts=trusted_image_hosts,
            )
        log_process_memory(
            logger,
            stage="wechat_cover_downloaded",
            worker_id=WORKER_ID,
            size=payload.size,
            file_backed=payload.is_file_backed,
        )
        return CoverImage(content=payload, content_type=payload.content_type, filename=payload.filename)

    async def create_draft(
        self,
        account: WeChatAccount,
        *,
        html: str,
        metadata: WeChatArticleMetadata,
        cover: CoverImage,
        cached_cover_media_id: str | None,
        cached_body_images: dict[str, BodyImageCacheEntry] | None = None,
        trusted_image_hosts: set[str] | None = None,
        local_image_loader: LocalImageLoader | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> DraftPushResult:
        return await self._push_draft_with_cleanup(
            account,
            html=html,
            metadata=metadata,
            cover=cover,
            cached_cover_media_id=cached_cover_media_id,
            cached_body_images=cached_body_images,
            trusted_image_hosts=trusted_image_hosts,
            local_image_loader=local_image_loader,
            progress_callback=progress_callback,
        )

    async def update_draft(
        self,
        account: WeChatAccount,
        *,
        target_media_id: str,
        html: str,
        metadata: WeChatArticleMetadata,
        cover: CoverImage,
        cached_cover_media_id: str | None,
        cached_body_images: dict[str, BodyImageCacheEntry] | None = None,
        trusted_image_hosts: set[str] | None = None,
        local_image_loader: LocalImageLoader | None = None,
        progress_callback: ProgressCallback | None = None,
        fallback_to_create_on_invalid_target: bool = False,
    ) -> DraftPushResult:
        target_media_id = target_media_id.strip()
        if not target_media_id:
            raise WeChatApiError("覆盖原图文时必须选择要覆盖的草稿")
        return await self._push_draft_with_cleanup(
            account,
            html=html,
            metadata=metadata,
            cover=cover,
            cached_cover_media_id=cached_cover_media_id,
            cached_body_images=cached_body_images,
            target_media_id=target_media_id,
            trusted_image_hosts=trusted_image_hosts,
            local_image_loader=local_image_loader,
            progress_callback=progress_callback,
            fallback_to_create_on_invalid_target=fallback_to_create_on_invalid_target,
        )

    async def _push_draft_with_cleanup(self, account: WeChatAccount, **kwargs: Any) -> DraftPushResult:
        cover = kwargs["cover"]
        assert isinstance(cover, CoverImage)
        log_process_memory(
            logger,
            stage="wechat_draft_start",
            worker_id=WORKER_ID,
            account_id=account.id,
            cover_file_backed=cover.payload.is_file_backed,
        )
        try:
            return await self._push_draft(account, **kwargs)
        finally:
            cover.close()
            log_process_memory(
                logger,
                stage="wechat_draft_end",
                worker_id=WORKER_ID,
                account_id=account.id,
            )

    async def list_draft_targets(self, account: WeChatAccount) -> list[DraftTarget]:
        """Return the account's most recently updated drafts for overwrite selection."""
        last_error: WeChatApiError | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), follow_redirects=False) as client:
                    token = await self._access_token(client, account, force_refresh=attempt > 0)
                    targets: list[DraftTarget] = []
                    offset = 0
                    total_count: int | None = None
                    while len(targets) < MAX_DRAFT_TARGETS and (total_count is None or offset < total_count):
                        payload = await self._wechat_json(
                            client,
                            "POST",
                            "/cgi-bin/draft/batchget",
                            token,
                            json={"offset": offset, "count": DRAFT_TARGET_PAGE_SIZE, "no_content": 1},
                        )
                        page_items = payload.get("item", [])
                        if page_items is None:
                            page_items = []
                        if not isinstance(page_items, list):
                            raise WeChatApiError("微信返回的草稿列表格式无效")
                        total_count = self._positive_int_or_none(payload.get("total_count"))
                        for item in page_items:
                            target = self._draft_target_from_list_item(item)
                            if target is not None:
                                targets.append(target)
                                if len(targets) >= MAX_DRAFT_TARGETS:
                                    break
                        if not page_items:
                            break
                        offset += len(page_items)
                    return targets
            except WeChatApiError as exc:
                last_error = exc
                if attempt == 0 and exc.code in TOKEN_ERROR_CODES:
                    await self._invalidate_token(account.id)
                    continue
                raise
        assert last_error is not None
        raise last_error

    async def validate_draft_target(self, account: WeChatAccount, target_media_id: str) -> DraftTarget:
        """Confirm the target exists in this account before uploading replacement assets."""
        target_media_id = target_media_id.strip()
        if not target_media_id:
            raise WeChatApiError("覆盖原图文时必须选择要覆盖的草稿")

        last_error: WeChatApiError | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), follow_redirects=False) as client:
                    token = await self._access_token(client, account, force_refresh=attempt > 0)
                    payload = await self._wechat_json(
                        client,
                        "POST",
                        "/cgi-bin/draft/get",
                        token,
                        json={"media_id": target_media_id},
                    )
                    news_items = payload.get("news_item")
                    if not isinstance(news_items, list) or not news_items:
                        raise WeChatApiError("要覆盖的草稿不存在，或不属于当前公众号")
                    first_article = news_items[0]
                    title = first_article.get("title") if isinstance(first_article, dict) else ""
                    return DraftTarget(
                        media_id=target_media_id,
                        title=str(title or "").strip() or "未命名草稿",
                        update_time=None,
                        article_count=len(news_items),
                    )
            except WeChatApiError as exc:
                last_error = exc
                if attempt == 0 and exc.code in TOKEN_ERROR_CODES:
                    await self._invalidate_token(account.id)
                    continue
                raise
        assert last_error is not None
        raise last_error

    async def _push_draft(
        self,
        account: WeChatAccount,
        *,
        html: str,
        metadata: WeChatArticleMetadata,
        cover: CoverImage,
        cached_cover_media_id: str | None,
        cached_body_images: dict[str, BodyImageCacheEntry] | None = None,
        target_media_id: str | None = None,
        trusted_image_hosts: set[str] | None = None,
        local_image_loader: LocalImageLoader | None = None,
        progress_callback: ProgressCallback | None = None,
        fallback_to_create_on_invalid_target: bool = False,
    ) -> DraftPushResult:
        self.validate_draft_input(metadata, html)

        last_error: WeChatApiError | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), follow_redirects=False) as client:
                    await self._report_progress(progress_callback, "token", 42, "正在获取公众号 access_token…")
                    token = await self._access_token(client, account, force_refresh=attempt > 0)
                    await self._report_progress(progress_callback, "token", 47, "公众号授权已确认，开始处理正文图片…")
                    image_result = await self._replace_body_images(
                        client,
                        token,
                        html,
                        trusted_image_hosts=trusted_image_hosts,
                        cached_body_images=cached_body_images,
                        local_image_loader=local_image_loader,
                        progress_callback=progress_callback,
                    )
                    self._ensure_publishable_body_image_sources(image_result.html)
                    # Recheck after WeChat image URLs have replaced the source URLs.
                    self._validate_article(metadata, image_result.html)
                    cover_media_id = cached_cover_media_id
                    uploaded_cover = False
                    if not cover_media_id:
                        await self._report_progress(progress_callback, "cover", 79, "正在上传封面永久素材…")
                        cover_media_id = await self._upload_cover(client, token, cover)
                        uploaded_cover = True
                        await self._report_progress(progress_callback, "cover", 86, "封面永久素材已上传…")
                    else:
                        await self._report_progress(progress_callback, "cover", 86, "已复用该公众号的封面永久素材…")
                    article = self._article_payload(metadata, image_result.html, cover_media_id)
                    created_new_draft = False
                    try:
                        media_id = await self._submit_draft(client, token, article, target_media_id, progress_callback)
                    except WeChatApiError as exc:
                        if (
                            fallback_to_create_on_invalid_target
                            and target_media_id
                            and exc.code == 40007
                        ):
                            await self._report_progress(
                                progress_callback,
                                "draft",
                                91,
                                "上次同步的微信草稿已不存在，正在创建新的草稿…",
                            )
                            media_id = await self._submit_draft(client, token, article, None, progress_callback)
                            created_new_draft = True
                        elif not image_result.cached_source_hashes or exc.code not in BODY_IMAGE_CACHE_RETRY_ERROR_CODES:
                            raise
                        else:
                            await self._report_progress(
                                progress_callback,
                                "body-images",
                                48,
                                "微信未接受已缓存图片，正在重新上传命中的正文图片后重试一次…",
                            )
                            refreshed_image_result = await self._replace_body_images(
                                client,
                                token,
                                html,
                                trusted_image_hosts=trusted_image_hosts,
                                cached_body_images=cached_body_images,
                                force_reupload_source_hashes=image_result.cached_source_hashes,
                                local_image_loader=local_image_loader,
                                progress_callback=progress_callback,
                            )
                            merged_cache_entries = {
                                entry.source_url_sha256: entry for entry in image_result.cache_entries
                            }
                            merged_cache_entries.update(
                                {entry.source_url_sha256: entry for entry in refreshed_image_result.cache_entries}
                            )
                            image_result = BodyImageReplacementResult(
                                html=refreshed_image_result.html,
                                cache_entries=tuple(merged_cache_entries.values()),
                                cached_source_hashes=refreshed_image_result.cached_source_hashes,
                            )
                            self._ensure_publishable_body_image_sources(image_result.html)
                            self._validate_article(metadata, image_result.html)
                            article = self._article_payload(metadata, image_result.html, cover_media_id)
                            media_id = await self._submit_draft(client, token, article, target_media_id, progress_callback)
                    await self._report_progress(progress_callback, "draft", 96, "微信草稿已写入，正在保存推送记录…")
                    return DraftPushResult(
                        media_id=media_id,
                        cover_media_id=cover_media_id,
                        cover_media_was_uploaded=uploaded_cover,
                        body_image_cache_entries=image_result.cache_entries,
                        created_new_draft=created_new_draft,
                    )
            except WeChatApiError as exc:
                last_error = exc
                if attempt == 0 and exc.code in TOKEN_ERROR_CODES:
                    await self._invalidate_token(account.id)
                    await self._report_progress(progress_callback, "token", 40, "微信 access_token 已失效，正在刷新后重试一次…")
                    continue
                raise
        assert last_error is not None
        raise last_error

    async def _submit_draft(
        self,
        client: httpx.AsyncClient,
        token: str,
        article: dict[str, Any],
        target_media_id: str | None,
        progress_callback: ProgressCallback | None,
    ) -> str:
        if target_media_id:
            await self._report_progress(progress_callback, "draft", 91, "正在覆盖上次同步草稿的首篇图文…")
            await self._wechat_json(
                client,
                "POST",
                "/cgi-bin/draft/update",
                token,
                json={"media_id": target_media_id, "index": 0, "articles": article},
            )
            return target_media_id
        await self._report_progress(progress_callback, "draft", 91, "正在创建微信草稿…")
        response = await self._wechat_json(
            client,
            "POST",
            "/cgi-bin/draft/add",
            token,
            json={"articles": [article]},
        )
        media_id = str(response.get("media_id") or "").strip()
        if not media_id:
            raise WeChatApiError("微信未返回草稿 media_id")
        return media_id

    @staticmethod
    def _positive_int_or_none(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    @classmethod
    def _draft_target_from_list_item(cls, item: Any) -> DraftTarget | None:
        if not isinstance(item, dict):
            return None
        media_id = str(item.get("media_id") or "").strip()
        content = item.get("content")
        news_items = content.get("news_item") if isinstance(content, dict) else None
        if not media_id or not isinstance(news_items, list) or not news_items:
            return None
        first_article = news_items[0]
        title = first_article.get("title") if isinstance(first_article, dict) else ""
        return DraftTarget(
            media_id=media_id,
            title=str(title or "").strip() or "未命名草稿",
            update_time=cls._positive_int_or_none(item.get("update_time")),
            article_count=len(news_items),
        )

    @staticmethod
    def validate_draft_input(metadata: WeChatArticleMetadata, html: str) -> None:
        validation = validate_html_structure(html)
        if not validation.valid:
            raise WeChatApiError(f"正文 HTML 结构无效：{validation.errors[0]}")
        if not html.strip():
            raise WeChatApiError("正文不能为空")
        WeChatOfficialAccountClient._validate_article(metadata, html)

    @staticmethod
    def body_image_sources(html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        sources: list[str] = []

        def add_source(value: str) -> None:
            source = unescape(value).strip()
            if source and source not in sources:
                sources.append(source)

        for image in soup.find_all("img"):
            source = image.get("src")
            if not isinstance(source, str) or not source.strip():
                raise WeChatApiError("正文存在未设置 src 的图片")
            add_source(source)
            srcset = image.get("srcset")
            if isinstance(srcset, str):
                for _start, _end, srcset_source in srcset_source_spans(srcset):
                    add_source(srcset_source)
        for element in soup.find_all(style=True):
            style = element.get("style")
            if not isinstance(style, str):
                continue
            for source in css_url_sources(style):
                add_source(source)
        return sources

    @staticmethod
    def _ensure_publishable_body_image_sources(html: str) -> None:
        for source in WeChatOfficialAccountClient.body_image_sources(html):
            parsed = urlsplit(source)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise WeChatApiError("正文图片地址必须在提交前转换为公开的 http:// 或 https:// URL")

    @staticmethod
    def body_image_source_sha256(source_url: str) -> str:
        return hashlib.sha256(source_url.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _transcode_body_image(payload: ImagePayload) -> ImagePayload:
        """Convert browser-supported WebP into a format accepted by WeChat."""
        if payload.content_type not in BODY_IMAGE_TRANSCODE_TYPES:
            raise WeChatApiError(f"正文图片格式 {payload.content_type or '未知'} 无法自动转换")

        output = BytesIO()
        output_type = ""
        extension = ""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(payload.rewind()) as image:
                    if image.format != "WEBP":
                        raise WeChatApiError("正文图片声明为 WebP，但文件内容不是有效的 WebP")
                    width, height = image.size
                    frame_count = int(getattr(image, "n_frames", 1) or 1)
                    if width <= 0 or height <= 0 or width * height > MAX_BODY_IMAGE_PIXELS:
                        raise WeChatApiError("正文 WebP 图片像素尺寸过大，无法安全转换")
                    if frame_count > MAX_BODY_IMAGE_ANIMATION_FRAMES:
                        raise WeChatApiError("正文 WebP 动画帧数过多，无法安全转换")
                    if width * height * frame_count > MAX_BODY_IMAGE_ANIMATION_PIXELS:
                        raise WeChatApiError("正文 WebP 动画总像素量过大，无法安全转换")

                    if frame_count > 1:
                        frames: list[Image.Image] = []
                        durations: list[int] = []
                        try:
                            for frame_index in range(frame_count):
                                image.seek(frame_index)
                                image.load()
                                frames.append(image.convert("RGBA"))
                                durations.append(max(20, int(image.info.get("duration", 100) or 100)))
                            frames[0].save(
                                output,
                                format="GIF",
                                save_all=True,
                                append_images=frames[1:],
                                duration=durations,
                                loop=int(image.info.get("loop", 0) or 0),
                                disposal=2,
                                optimize=True,
                            )
                        finally:
                            for frame in frames:
                                frame.close()
                        output_type = "image/gif"
                        extension = ".gif"
                    else:
                        image.load()
                        oriented = ImageOps.exif_transpose(image)
                        try:
                            has_alpha = "A" in oriented.getbands() or (
                                oriented.mode == "P" and "transparency" in oriented.info
                            )
                            if has_alpha:
                                rgba = oriented.convert("RGBA")
                                try:
                                    rgba.save(output, format="PNG", optimize=True)
                                    if output.tell() > BODY_IMAGE_LIMIT:
                                        output.seek(0)
                                        output.truncate()
                                        background = Image.new("RGB", rgba.size, "white")
                                        try:
                                            background.paste(rgba, mask=rgba.getchannel("A"))
                                            background.save(
                                                output, format="JPEG", quality=90, optimize=True, progressive=True
                                            )
                                        finally:
                                            background.close()
                                        output_type = "image/jpeg"
                                        extension = ".jpg"
                                    else:
                                        output_type = "image/png"
                                        extension = ".png"
                                finally:
                                    rgba.close()
                            else:
                                rgb = oriented.convert("RGB")
                                try:
                                    rgb.save(output, format="JPEG", quality=90, optimize=True, progressive=True)
                                finally:
                                    rgb.close()
                                output_type = "image/jpeg"
                                extension = ".jpg"
                        finally:
                            if oriented is not image:
                                oriented.close()
        except WeChatApiError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as exc:
            raise WeChatApiError("正文 WebP 图片无法解码或转换，请重新上传为 JPG 或 PNG") from exc

        content = output.getvalue()
        if not content:
            raise WeChatApiError("正文 WebP 图片转换结果为空")
        if len(content) > BODY_IMAGE_LIMIT:
            raise WeChatApiError(f"正文 WebP 图片转换后超过 {BODY_IMAGE_LIMIT // (1024 * 1024)} MB")
        stem = PurePosixPath(payload.filename).stem or "body-image"
        return ImagePayload.from_bytes(content, content_type=output_type, filename=f"{stem}{extension}")

    async def _access_token(
        self, client: httpx.AsyncClient, account: WeChatAccount, *, force_refresh: bool = False
    ) -> str:
        now = time.monotonic()
        if not force_refresh:
            async with self._cache_lock:
                cached = self._token_cache.get(account.id)
                if cached and cached[1] > now:
                    return cached[0]

        secret = decrypt_secret(account.app_secret_encrypted)
        try:
            response = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/stable_token",
                json={
                    "grant_type": "client_credential",
                    "appid": account.app_id,
                    "secret": secret,
                    "force_refresh": bool(force_refresh),
                },
            )
            payload = self._response_json(response)
        except httpx.HTTPError as exc:
            raise WeChatApiError(f"无法连接微信接口：{_redact_sensitive_text(str(exc))}") from exc
        self._raise_wechat_error(payload, response.status_code)
        token = str(payload.get("access_token") or "").strip()
        expires_in = int(payload.get("expires_in") or 0)
        if not token or expires_in <= 0:
            raise WeChatApiError("微信未返回有效的 access_token")
        async with self._cache_lock:
            self._token_cache[account.id] = (
                token,
                time.monotonic() + max(1, expires_in - TOKEN_REFRESH_MARGIN_SECONDS),
            )
        return token

    async def _invalidate_token(self, account_id: int) -> None:
        async with self._cache_lock:
            self._token_cache.pop(account_id, None)

    async def _replace_body_images(
        self,
        client: httpx.AsyncClient,
        token: str,
        html: str,
        *,
        trusted_image_hosts: set[str] | None = None,
        cached_body_images: dict[str, BodyImageCacheEntry] | None = None,
        force_reupload_source_hashes: frozenset[str] = frozenset(),
        local_image_loader: LocalImageLoader | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> BodyImageReplacementResult:
        soup = BeautifulSoup(html, "html.parser")
        sources = self.body_image_sources(html)
        cached_by_source = cached_body_images or {}
        cached_by_content: dict[str, BodyImageCacheEntry] = {}
        for entry in cached_by_source.values():
            if self._is_reusable_body_image(entry):
                cached_by_content.setdefault(entry.content_sha256, entry)

        replacements: dict[str, str] = {}
        cache_entries: list[BodyImageCacheEntry] = []
        cached_source_hashes: set[str] = set()
        if not sources:
            await self._report_progress(progress_callback, "body-images", 76, "正文没有图片，已跳过正文图片同步…")

        total = len(sources)
        for index, source in enumerate(sources, start=1):
            source_hash = self.body_image_source_sha256(source)
            cached_entry = cached_by_source.get(source_hash)
            if (
                cached_entry is not None
                and self._is_reusable_body_image(cached_entry)
                and source_hash not in force_reupload_source_hashes
            ):
                replacements[source] = cached_entry.wechat_url
                cached_source_hashes.add(source_hash)
                await self._report_progress(
                    progress_callback,
                    "body-images",
                    47 + (index * 29 // total),
                    f"正文图片 {index}/{total}：已命中微信图片缓存，无需下载和上传…",
                )
                continue
            await self._report_progress(
                progress_callback,
                "body-images",
                47 + ((index - 1) * 29 // total),
                f"正文图片 {index}/{total}：正在下载并校验格式与大小…",
            )
            local_image = local_image_loader(source) if local_image_loader is not None else None
            if isinstance(local_image, ImagePayload):
                payload = local_image
            elif local_image is None:
                payload = await self._download_image(
                    client,
                    source,
                    allowed_types=BODY_IMAGE_SOURCE_TYPES,
                    max_bytes=BODY_IMAGE_LIMIT,
                    label="正文图片",
                    trusted_image_hosts=trusted_image_hosts,
                )
            else:
                content, content_type, filename = local_image
                payload = ImagePayload.from_bytes(content, content_type=content_type, filename=filename)

            log_process_memory(
                logger,
                stage="wechat_body_image_ready",
                worker_id=WORKER_ID,
                size=payload.size,
                file_backed=payload.is_file_backed,
                image_index=index,
            )
            try:
                if payload.content_type in BODY_IMAGE_TRANSCODE_TYPES:
                    await self._report_progress(
                        progress_callback,
                        "body-images",
                        48 + ((index - 1) * 29 // total),
                        f"正文图片 {index}/{total}：正在将 WebP 转换为微信支持的格式…",
                    )
                    converted_payload = await asyncio.to_thread(self._transcode_body_image, payload)
                    payload.close()
                    payload = converted_payload
                content_type = payload.content_type
                if content_type not in BODY_IMAGE_TYPES:
                    raise WeChatApiError(f"正文图片仅支持 {'、'.join(sorted(BODY_IMAGE_TYPES))} 格式")
                if payload.size <= 0:
                    raise WeChatApiError("正文图片为空")
                if payload.size > BODY_IMAGE_LIMIT:
                    raise WeChatApiError(f"正文图片不能超过 {BODY_IMAGE_LIMIT // (1024 * 1024)} MB")
                content_hash = payload.content_sha256
                content_cached_entry = cached_by_content.get(content_hash)
                if content_cached_entry is not None and source_hash not in force_reupload_source_hashes:
                    replacements[source] = content_cached_entry.wechat_url
                    cached_source_hashes.add(source_hash)
                    cache_entries.append(
                        BodyImageCacheEntry(
                            source_url_sha256=source_hash,
                            content_sha256=content_hash,
                            content_type=content_type,
                            wechat_url=content_cached_entry.wechat_url,
                            upload_mode=content_cached_entry.upload_mode,
                        )
                    )
                    await self._report_progress(
                        progress_callback,
                        "body-images",
                        47 + (index * 29 // total),
                        f"正文图片 {index}/{total}：内容未变化，已复用微信图片素材…",
                    )
                    continue

                if content_type in TEMPORARY_BODY_IMAGE_TYPES and payload.size <= TEMPORARY_BODY_IMAGE_LIMIT:
                    await self._report_progress(
                        progress_callback,
                        "body-images",
                        49 + ((index - 1) * 29 // total),
                        f"正文图片 {index}/{total}：正在上传微信正文图片素材（{content_type}，{payload.size // 1024} KB）…",
                    )
                    wechat_url = await self._upload_article_image(client, token, payload=payload)
                    upload_mode = "uploadimg"
                else:
                    await self._report_progress(
                        progress_callback,
                        "body-images",
                        49 + ((index - 1) * 29 // total),
                        f"正文图片 {index}/{total}：正在上传微信永久素材（{content_type}，{payload.size // 1024} KB）…",
                    )
                    permanent_image = await self._upload_permanent_image(
                        client,
                        token,
                        payload=payload,
                        require_url=True,
                    )
                    wechat_url = permanent_image.url
                    upload_mode = "permanent"
                log_process_memory(
                    logger,
                    stage="wechat_body_image_uploaded",
                    worker_id=WORKER_ID,
                    size=payload.size,
                    file_backed=payload.is_file_backed,
                    image_index=index,
                )
                replacements[source] = wechat_url
                cache_entry = BodyImageCacheEntry(
                    source_url_sha256=source_hash,
                    content_sha256=content_hash,
                    content_type=content_type,
                    wechat_url=wechat_url,
                    upload_mode=upload_mode,
                )
                cache_entries.append(cache_entry)
                cached_by_content.setdefault(content_hash, cache_entry)
                await self._report_progress(
                    progress_callback,
                    "body-images",
                    47 + (index * 29 // total),
                    f"正文图片 {index}/{total} 已同步到微信…",
                )
            finally:
                payload.close()

        for element in soup.find_all(style=True):
            style = element.get("style")
            if isinstance(style, str):
                element["style"] = replace_css_urls(style, replacements)
        for image in soup.find_all("img"):
            source = image.get("src")
            if isinstance(source, str):
                replacement = replacements.get(unescape(source).strip())
                if replacement:
                    image["src"] = replacement
            srcset = image.get("srcset")
            if isinstance(srcset, str):
                image["srcset"] = replace_srcset_sources(srcset, replacements)
        return BodyImageReplacementResult(
            html=str(soup),
            cache_entries=tuple(cache_entries),
            cached_source_hashes=frozenset(cached_source_hashes),
        )

    @staticmethod
    def _is_reusable_body_image(entry: BodyImageCacheEntry) -> bool:
        """Only trust URLs created by the current article-image upload path.

        Cached URLs from prior releases use a different marker and are uploaded
        again, preventing an old or invalid material URL from reaching a draft.
        """
        return entry.upload_mode == "uploadimg"

    @staticmethod
    async def _report_progress(
        progress_callback: ProgressCallback | None,
        stage: str,
        percent: int,
        detail: str,
    ) -> None:
        if progress_callback is not None:
            await progress_callback(stage, percent, detail)

    async def _upload_cover(self, client: httpx.AsyncClient, token: str, cover: CoverImage) -> str:
        permanent_image = await self._upload_permanent_image(
            client,
            token,
            payload=cover.payload,
            require_url=False,
        )
        return permanent_image.media_id

    async def _upload_article_image(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        payload: ImagePayload,
    ) -> str:
        response_payload = await self._wechat_json(
            client,
            "POST",
            "/cgi-bin/media/uploadimg",
            token,
            files={"media": (payload.filename, payload.rewind(), payload.content_type)},
        )
        url = str(response_payload.get("url") or "").strip()
        if not url:
            raise WeChatApiError("微信未返回正文临时素材 URL")
        return url

    async def _upload_permanent_image(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        payload: ImagePayload,
        require_url: bool,
    ) -> PermanentImage:
        payload.rewind()
        response_payload = await self._wechat_json(
            client,
            "POST",
            "/cgi-bin/material/add_material",
            token,
            params={"type": "image"},
            files={"media": (payload.filename, payload.rewind(), payload.content_type)},
        )
        media_id = str(response_payload.get("media_id") or "").strip()
        if not media_id:
            raise WeChatApiError("微信未返回图片永久素材 media_id")
        url = str(response_payload.get("url") or "").strip()
        if require_url and not url:
            raise WeChatApiError("微信未返回正文永久素材 URL")
        return PermanentImage(media_id=media_id, url=url)

    async def _wechat_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        token: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        params = dict(kwargs.pop("params", {}) or {})
        params["access_token"] = token
        try:
            response = await client.request(method, f"{WECHAT_API_BASE}{path}", params=params, **kwargs)
            payload = self._response_json(response)
        except httpx.HTTPError as exc:
            raise WeChatApiError(f"微信接口请求失败：{_redact_sensitive_text(str(exc))}") from exc
        self._raise_wechat_error(payload, response.status_code)
        return payload

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeChatApiError(f"微信接口返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if not isinstance(payload, dict):
            raise WeChatApiError("微信接口返回格式无效")
        return payload

    @staticmethod
    def _raise_wechat_error(payload: dict[str, Any], status_code: int) -> None:
        error_code = payload.get("errcode")
        if isinstance(error_code, bool):
            error_code = None
        try:
            error_code = int(error_code) if error_code is not None else None
        except (TypeError, ValueError):
            error_code = None
        if status_code >= 400 or (error_code is not None and error_code != 0):
            message = _redact_sensitive_text(str(payload.get("errmsg") or f"微信接口错误（HTTP {status_code}）"))
            if error_code is not None:
                message = f"微信错误 {error_code}：{message}"
            raise WeChatApiError(message, error_code)

    async def _download_image(
        self,
        client: httpx.AsyncClient,
        source_url: str,
        *,
        allowed_types: set[str],
        max_bytes: int,
        label: str,
        trusted_image_hosts: set[str] | None = None,
    ) -> ImagePayload:
        url = source_url.strip()
        for _ in range(MAX_REDIRECTS + 1):
            await self._validate_public_url(url, trusted_image_hosts=trusted_image_hosts)
            try:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise WeChatApiError(f"{label}重定向地址为空")
                        url = urljoin(url, location)
                        continue
                    if response.status_code >= 400:
                        raise WeChatApiError(f"下载{label}失败（HTTP {response.status_code}）")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in allowed_types:
                        supported = "、".join(sorted(allowed_types))
                        raise WeChatApiError(f"{label}仅支持 {supported} 格式")
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            declared_size = 0
                        if declared_size > max_bytes:
                            raise WeChatApiError(f"{label}不能超过 {max_bytes // (1024 * 1024)} MB")
                    stream = SpooledTemporaryFile(max_size=IMAGE_MEMORY_BUFFER_LIMIT, mode="w+b")
                    digest = hashlib.sha256()
                    size = 0
                    try:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise WeChatApiError(f"{label}不能超过 {max_bytes // (1024 * 1024)} MB")
                            stream.write(chunk)
                            digest.update(chunk)
                        if size <= 0:
                            raise WeChatApiError(f"{label}为空")
                        stream.seek(0)
                    except BaseException:
                        stream.close()
                        raise
            except httpx.HTTPError as exc:
                raise WeChatApiError(f"下载{label}失败：{_redact_sensitive_text(str(exc))}") from exc
            filename = PurePosixPath(urlsplit(url).path).name or f"image{IMAGE_EXTENSIONS[content_type]}"
            if not filename.lower().endswith(IMAGE_EXTENSIONS[content_type]):
                filename = f"{filename}{IMAGE_EXTENSIONS[content_type]}"
            return ImagePayload(
                stream,
                content_type=content_type,
                filename=filename,
                size=size,
                content_sha256=digest.hexdigest(),
            )
        raise WeChatApiError(f"{label}重定向次数过多")

    @staticmethod
    async def _validate_public_url(value: str, *, trusted_image_hosts: set[str] | None = None) -> None:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise WeChatApiError("图片地址必须是公开的 http:// 或 https:// URL")
        if parsed.port not in {None, 80, 443}:
            raise WeChatApiError("图片地址不能使用非标准端口")
        try:
            resolved = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)),
            )
        except socket.gaierror as exc:
            raise WeChatApiError("图片地址无法解析") from exc
        addresses = {item[4][0] for item in resolved}
        if not addresses:
            raise WeChatApiError("图片地址无法解析")
        hostname = parsed.hostname.rstrip(".").lower()
        trusted_hosts = {host.rstrip(".").lower() for host in trusted_image_hosts or set()}
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
                if not parsed_address.is_global and not WeChatOfficialAccountClient._is_trusted_oss_benchmark_address(
                    hostname, parsed_address, trusted_hosts
                ):
                    raise WeChatApiError("图片地址不能指向内网或本机地址")
            except ValueError as exc:
                raise WeChatApiError("图片地址解析结果无效") from exc

    @staticmethod
    def _is_trusted_oss_benchmark_address(
        hostname: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address, trusted_hosts: set[str]
    ) -> bool:
        return hostname in trusted_hosts and address.version == 4 and address in TRUSTED_OSS_BENCHMARK_NETWORK

    @staticmethod
    def _validate_article(metadata: WeChatArticleMetadata, content: str) -> None:
        if not metadata.title or len(metadata.title) > 32:
            raise WeChatApiError("请填写不超过 32 个字的微信标题")
        if not metadata.cover_url:
            raise WeChatApiError("请先上传封面")

    @staticmethod
    def _article_payload(
        metadata: WeChatArticleMetadata, content: str, cover_media_id: str
    ) -> dict[str, Any]:
        article: dict[str, Any] = {
            "article_type": "news",
            "title": metadata.title,
            "author": metadata.author,
            "digest": metadata.digest or WECHAT_EMPTY_DIGEST_PLACEHOLDER,
            "content": content,
            "content_source_url": metadata.content_source_url,
            "thumb_media_id": cover_media_id,
            "need_open_comment": 1 if metadata.need_open_comment else 0,
            "only_fans_can_comment": 1 if metadata.need_open_comment and metadata.only_fans_can_comment else 0,
        }
        if metadata.pic_crop_235_1:
            article["pic_crop_235_1"] = metadata.pic_crop_235_1
        if metadata.pic_crop_1_1:
            article["pic_crop_1_1"] = metadata.pic_crop_1_1
        return article
