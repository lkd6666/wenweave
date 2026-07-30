"""Server-side integration with WeChat Official Account draft APIs."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.core.crypto import decrypt_secret
from app.models.wechat_account import WeChatAccount
from app.schemas.wechat import WeChatArticleMetadata
from app.services.html_validation import validate_html_structure


WECHAT_API_BASE = "https://api.weixin.qq.com"
TOKEN_REFRESH_MARGIN_SECONDS = 300
PERMANENT_IMAGE_LIMIT = 10 * 1024 * 1024
BODY_IMAGE_LIMIT = PERMANENT_IMAGE_LIMIT
TEMPORARY_BODY_IMAGE_LIMIT = 1 * 1024 * 1024
COVER_IMAGE_LIMIT = PERMANENT_IMAGE_LIMIT
MAX_REDIRECTS = 3
TOKEN_ERROR_CODES = {40001, 40014, 42001}
BODY_IMAGE_CACHE_RETRY_ERROR_CODES = {40007, 40008, 47001}
TRUSTED_OSS_BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")
COVER_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp"}
BODY_IMAGE_TYPES = COVER_IMAGE_TYPES
TEMPORARY_BODY_IMAGE_TYPES = {"image/jpeg", "image/png"}
MAX_DRAFT_TARGETS = 100
DRAFT_TARGET_PAGE_SIZE = 20
MINI_PROGRAM_ATTRIBUTE_PREFIX = "data-miniprogram-"
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


class WeChatApiError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CoverImage:
    content: bytes
    content_type: str
    filename: str

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


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


@dataclass(frozen=True)
class DraftTarget:
    media_id: str
    title: str
    update_time: int | None
    article_count: int


ProgressCallback = Callable[[str, int, str], Awaitable[None]]
LocalImageLoader = Callable[[str], tuple[bytes, str, str] | None]


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
            content, content_type, filename = await self._download_image(
                client,
                source_url,
                allowed_types=COVER_IMAGE_TYPES,
                max_bytes=COVER_IMAGE_LIMIT,
                label="封面",
                trusted_image_hosts=trusted_image_hosts,
            )
        return CoverImage(content=content, content_type=content_type, filename=filename)

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
        return await self._push_draft(
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
    ) -> DraftPushResult:
        target_media_id = target_media_id.strip()
        if not target_media_id:
            raise WeChatApiError("覆盖原图文时必须选择要覆盖的草稿")
        return await self._push_draft(
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
    ) -> DraftPushResult:
        html = self.downgrade_mini_program_text_links(html)
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
                    try:
                        media_id = await self._submit_draft(client, token, article, target_media_id, progress_callback)
                    except WeChatApiError as exc:
                        if not image_result.cached_source_hashes or exc.code not in BODY_IMAGE_CACHE_RETRY_ERROR_CODES:
                            raise
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
                        self._validate_article(metadata, image_result.html)
                        article = self._article_payload(metadata, image_result.html, cover_media_id)
                        media_id = await self._submit_draft(client, token, article, target_media_id, progress_callback)
                    await self._report_progress(progress_callback, "draft", 96, "微信草稿已写入，正在保存推送记录…")
                    return DraftPushResult(
                        media_id=media_id,
                        cover_media_id=cover_media_id,
                        cover_media_was_uploaded=uploaded_cover,
                        body_image_cache_entries=image_result.cache_entries,
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
    def downgrade_mini_program_text_links(html: str) -> str:
        """Keep pasted mini-program link text, but prevent attachment-card rendering."""
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a"):
            classes = link.get("class") or []
            has_mini_program_class = "weapp_text_link" in classes
            mini_program_attributes = [
                name for name in link.attrs if name.lower().startswith(MINI_PROGRAM_ATTRIBUTE_PREFIX)
            ]
            if not has_mini_program_class and not mini_program_attributes:
                continue

            remaining_classes = [name for name in classes if name != "weapp_text_link"]
            if remaining_classes:
                link["class"] = remaining_classes
            else:
                link.attrs.pop("class", None)
            for name in mini_program_attributes:
                link.attrs.pop(name, None)

            style = str(link.get("style") or "").strip().rstrip(";")
            style_properties = {
                declaration.split(":", 1)[0].strip().lower()
                for declaration in style.split(";")
                if ":" in declaration
            }
            defaults: list[str] = []
            if "font-size" not in style_properties:
                defaults.append("font-size:15px")
            if "color" not in style_properties:
                defaults.append("color:#576b95")
            if not any(name.startswith("text-decoration") for name in style_properties):
                defaults.append("text-decoration:none")
            if defaults:
                style = ";".join(part for part in (style, *defaults) if part)
                link["style"] = f"{style};"
        return "".join(str(node) for node in soup.contents)

    @staticmethod
    def body_image_sources(html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        sources: list[str] = []
        for image in soup.find_all("img"):
            source = image.get("src")
            if not isinstance(source, str) or not source.strip():
                raise WeChatApiError("正文存在未设置 src 的图片")
            source = source.strip()
            if source not in sources:
                sources.append(source)
        return sources

    @staticmethod
    def body_image_source_sha256(source_url: str) -> str:
        return hashlib.sha256(source_url.strip().encode("utf-8")).hexdigest()

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
            raise WeChatApiError(f"无法连接微信接口：{exc}") from exc
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
            if cached_entry is not None and source_hash not in force_reupload_source_hashes:
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
            if local_image is None:
                content, content_type, filename = await self._download_image(
                    client,
                    source,
                    allowed_types=BODY_IMAGE_TYPES,
                    max_bytes=BODY_IMAGE_LIMIT,
                    label="正文图片",
                    trusted_image_hosts=trusted_image_hosts,
                )
            else:
                content, content_type, filename = local_image
                if content_type not in BODY_IMAGE_TYPES:
                    raise WeChatApiError(f"正文图片仅支持 {'、'.join(sorted(BODY_IMAGE_TYPES))} 格式")
                if not content:
                    raise WeChatApiError("正文图片为空")
                if len(content) > BODY_IMAGE_LIMIT:
                    raise WeChatApiError(f"正文图片不能超过 {BODY_IMAGE_LIMIT // (1024 * 1024)} MB")
            content_hash = hashlib.sha256(content).hexdigest()
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

            if content_type in TEMPORARY_BODY_IMAGE_TYPES and len(content) <= TEMPORARY_BODY_IMAGE_LIMIT:
                await self._report_progress(
                    progress_callback,
                    "body-images",
                    49 + ((index - 1) * 29 // total),
                    f"正文图片 {index}/{total}：正在上传微信正文图片素材（{content_type}，{len(content) // 1024} KB）…",
                )
                wechat_url = await self._upload_article_image(
                    client,
                    token,
                    content=content,
                    content_type=content_type,
                    filename=filename,
                )
                upload_mode = "temporary"
            else:
                await self._report_progress(
                    progress_callback,
                    "body-images",
                    49 + ((index - 1) * 29 // total),
                    f"正文图片 {index}/{total}：正在上传微信永久素材（{content_type}，{len(content) // 1024} KB）…",
                )
                permanent_image = await self._upload_permanent_image(
                    client,
                    token,
                    content=content,
                    content_type=content_type,
                    filename=filename,
                    require_url=True,
                )
                wechat_url = permanent_image.url
                upload_mode = "permanent"
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

        for image in soup.find_all("img"):
            source = image.get("src")
            if isinstance(source, str) and source in replacements:
                image["src"] = replacements[source]
        return BodyImageReplacementResult(
            html=str(soup),
            cache_entries=tuple(cache_entries),
            cached_source_hashes=frozenset(cached_source_hashes),
        )

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
            content=cover.content,
            content_type=cover.content_type,
            filename=cover.filename,
            require_url=False,
        )
        return permanent_image.media_id

    async def _upload_article_image(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        content: bytes,
        content_type: str,
        filename: str,
    ) -> str:
        payload = await self._wechat_json(
            client,
            "POST",
            "/cgi-bin/media/uploadimg",
            token,
            files={"media": (filename, content, content_type)},
        )
        url = str(payload.get("url") or "").strip()
        if not url:
            raise WeChatApiError("微信未返回正文临时素材 URL")
        return url

    async def _upload_permanent_image(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        content: bytes,
        content_type: str,
        filename: str,
        require_url: bool,
    ) -> PermanentImage:
        payload = await self._wechat_json(
            client,
            "POST",
            "/cgi-bin/material/add_material",
            token,
            params={"type": "image"},
            files={"media": (filename, content, content_type)},
        )
        media_id = str(payload.get("media_id") or "").strip()
        if not media_id:
            raise WeChatApiError("微信未返回图片永久素材 media_id")
        url = str(payload.get("url") or "").strip()
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
            raise WeChatApiError(f"微信接口请求失败：{exc}") from exc
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
            message = str(payload.get("errmsg") or f"微信接口错误（HTTP {status_code}）")
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
    ) -> tuple[bytes, str, str]:
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
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise WeChatApiError(f"{label}不能超过 {max_bytes // (1024 * 1024)} MB")
                    if not content:
                        raise WeChatApiError(f"{label}为空")
            except httpx.HTTPError as exc:
                raise WeChatApiError(f"下载{label}失败：{exc}") from exc
            filename = PurePosixPath(urlsplit(url).path).name or f"image{IMAGE_EXTENSIONS[content_type]}"
            if not filename.lower().endswith(IMAGE_EXTENSIONS[content_type]):
                filename = f"{filename}{IMAGE_EXTENSIONS[content_type]}"
            return bytes(content), content_type, filename
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
            "digest": metadata.digest,
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
