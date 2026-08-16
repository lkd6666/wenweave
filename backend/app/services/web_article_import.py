"""Parse public articles into short-lived, user-scoped import previews."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import re
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from urllib.parse import quote, urljoin, urlsplit
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.document import Document, DocumentSourceType
from app.models.document_version import DocumentVersionSource
from app.models.web_article_import import WebArticleImport, WebArticleImportAsset, WebArticleImportStatus
from app.models.user import User
from app.models.layout_capture_session import LayoutCaptureSession
from app.services import local_uploads
from app.services.browser_capture import (
    CAPTURE_PURPOSE_WEB_ARTICLE_IMPORT,
    BrowserCaptureError,
    BrowserCaptureExpiredError,
    MAX_CAPTURE_ASSETS,
    MAX_CAPTURE_HTML_BYTES,
    MAX_CAPTURE_IMAGE_BYTES,
    MAX_CAPTURE_IMAGE_TOTAL_BYTES,
    WechatVerificationRequiredError,
    complete_browser_capture_session,
    create_browser_capture_session,
    is_wechat_verification_page,
    load_browser_capture_session,
    resolve_wechat_capture_url,
)
from app.services.document_images import DocumentImageStorageError, store_document_image
from app.services.document_versions import create_document_version
from app.services.chat_sessions import ensure_default_chat_session
from app.services.external_fetch import PublicFetchError, fetch_public_html, fetch_public_image
from app.services.html_validation import validate_html_structure


WEB_ARTICLE_IMPORT_TTL = timedelta(minutes=15)
MAX_ARTICLE_IMAGES = 50
IMAGE_FETCH_CONCURRENCY = 4
_ASSET_URL_PREFIX = "web-article-import://asset/"
_WECHAT_HOST = "mp.weixin.qq.com"
_WECHAT_COVER_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp"}
_ALLOWED_TAGS = {
    "article", "section", "div", "p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i",
    "u", "s", "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "br", "hr",
    "pre", "code", "figure", "figcaption", "small", "sup", "sub", "a", "img",
}
_DISCARDED_TAGS = {
    "script", "style", "iframe", "object", "embed", "template", "noscript", "svg", "canvas", "form", "button", "input",
    "video", "audio", "source", "track", "dialog",
}
_DANGEROUS_STYLE = re.compile(r"(?:expression\s*\(|@import|behavior\s*:|-moz-binding|url\s*\()", re.IGNORECASE)
_CAPTURE_DANGEROUS_STYLE = re.compile(r"(?:expression\s*\(|@import|behavior\s*:|-moz-binding)", re.IGNORECASE)
_CAPTURE_ASSET_URL_RE = re.compile(r"^layout-capture://([a-f0-9]{32})$", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<url>.*?)(?P=quote)\s*\)", re.IGNORECASE | re.DOTALL)
_IMAGE_SOURCE_ATTRIBUTES = ("data-src", "data-original", "data-actualsrc", "src")
CapturedAsset = tuple[str, str, str, bytes, int, int]


class WebArticleImportError(ValueError):
    pass


class WebArticleImportExpiredError(WebArticleImportError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _safe_style(value: str) -> str:
    clean = value.strip()
    if not clean or _DANGEROUS_STYLE.search(clean):
        return ""
    declarations: list[str] = []
    for declaration in clean.split(";"):
        name, separator, raw_value = declaration.partition(":")
        if not separator:
            continue
        normalized_name = name.strip().lower()
        normalized_value = raw_value.strip()
        if not normalized_name or not normalized_value:
            continue
        hidden_value = normalized_value.lower().replace("!important", "").strip()
        if normalized_name == "display" and hidden_value == "none":
            continue
        if normalized_name == "visibility" and hidden_value in {"hidden", "collapse"}:
            continue
        declarations.append(f"{normalized_name}:{normalized_value}")
    return ";".join(declarations)[:2000]


def _safe_link(raw_url: str, canonical_url: str) -> str:
    value = html.unescape(raw_url).strip()
    if not value:
        return ""
    if value.startswith("#"):
        return value
    resolved = urljoin(canonical_url, value)
    try:
        parsed = urlsplit(resolved)
    except ValueError:
        return ""
    return resolved if parsed.scheme.lower() in {"https", "mailto", "tel"} else ""


def _safe_image_source(raw_url: str, canonical_url: str) -> str:
    value = html.unescape(raw_url).strip()
    if not value:
        return ""
    if value.lower().startswith("data:"):
        return value
    resolved = urljoin(canonical_url, value)
    try:
        parsed = urlsplit(resolved)
    except ValueError:
        return ""
    return resolved if parsed.scheme.lower() == "https" and bool(parsed.hostname) else ""


def _article_title(soup: BeautifulSoup) -> str:
    for selector in ("meta[property='og:title']", "meta[name='twitter:title']"):
        meta = soup.select_one(selector)
        if meta and meta.get("content"):
            value = str(meta.get("content"))
            if value.strip():
                return re.sub(r"\s+", " ", value).strip()[:256]
    for selector in ("#activity-name", "title", "h1"):
        node = soup.select_one(selector)
        if node:
            value = node.get_text(" ", strip=True)
            if value:
                return re.sub(r"\s+", " ", value).strip()[:256]
    return "未命名推文"


def _is_wechat_article(canonical_url: str) -> bool:
    host = (urlsplit(canonical_url).hostname or "").lower()
    return host == _WECHAT_HOST or host.endswith(f".{_WECHAT_HOST}")


def _select_article_root(soup: BeautifulSoup, canonical_url: str) -> Tag | None:
    if _is_wechat_article(canonical_url):
        target = soup.select_one("#js_content")
        if target:
            return target
    return soup.select_one("article") or soup.select_one("main") or soup.body


def _sanitize_article(source: str, canonical_url: str) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(source, "html.parser")
    title = _article_title(soup)
    root = _select_article_root(soup, canonical_url)
    if root is None:
        raise WebArticleImportError("未能从页面提取可用正文，请尝试公开文章链接")
    for tag in root.find_all(list(_DISCARDED_TAGS)):
        tag.decompose()

    fragment = BeautifulSoup("<section></section>", "html.parser")
    container = fragment.section
    assert container is not None
    for child in list(root.contents):
        container.append(child.extract())

    for tag in list(container.find_all(True)):
        name = tag.name.lower()
        if name in _DISCARDED_TAGS:
            tag.decompose()
            continue
        if name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue
        attributes: dict[str, str] = {}
        if tag.has_attr("style"):
            style = _safe_style(str(tag.get("style") or ""))
            if style:
                attributes["style"] = style
        for name in ("align", "valign", "colspan", "rowspan", "width", "height"):
            value = str(tag.get(name) or "").strip()
            if value and len(value) <= 32:
                attributes[name] = value
        if tag.name == "a":
            href = _safe_link(str(tag.get("href") or ""), canonical_url)
            if href:
                attributes["href"] = href
        if tag.name == "img":
            raw_source = next((str(tag.get(name) or "").strip() for name in _IMAGE_SOURCE_ATTRIBUTES if tag.get(name)), "")
            image_source = _safe_image_source(raw_source, canonical_url)
            if not image_source:
                tag.decompose()
                continue
            attributes["src"] = image_source
            alt = str(tag.get("alt") or "").strip()
            if alt:
                attributes["alt"] = alt[:512]
        tag.attrs = attributes

    rendered = str(container)
    plain = re.sub(r"\s+", " ", container.get_text(" ", strip=True)).strip()
    if not plain and not container.find("img"):
        raise WebArticleImportError("未能从页面提取可用正文，请尝试公开文章链接")
    if len(rendered.encode("utf-8")) > get_settings().MAX_DOCUMENT_HTML_BYTES:
        raise WebArticleImportError("文章正文超过允许大小")
    return title, rendered, []


def _captured_style(value: str) -> tuple[str, set[str]]:
    clean = value.strip()
    if not clean or _CAPTURE_DANGEROUS_STYLE.search(clean):
        return "", set()
    declarations: list[str] = []
    used_ids: set[str] = set()
    for declaration in clean.split(";"):
        name, separator, raw_value = declaration.partition(":")
        if not separator:
            continue
        normalized_name = name.strip().lower()
        normalized_value = raw_value.strip()
        if not normalized_name or not normalized_value:
            continue
        hidden_value = normalized_value.lower().replace("!important", "").strip()
        if normalized_name == "display" and hidden_value == "none":
            continue
        if normalized_name == "visibility" and hidden_value in {"hidden", "collapse"}:
            continue
        if "url(" in normalized_value.lower():
            matches = list(_CSS_URL_RE.finditer(normalized_value))
            if not matches:
                continue
            valid = True
            declaration_ids: set[str] = set()

            def replace_url(match: re.Match[str]) -> str:
                nonlocal valid
                captured = _CAPTURE_ASSET_URL_RE.fullmatch(match.group("url").strip())
                if captured is None:
                    valid = False
                    return ""
                asset_id = captured.group(1).lower()
                declaration_ids.add(asset_id)
                return f'url("{_ASSET_URL_PREFIX}{asset_id}")'

            rewritten = _CSS_URL_RE.sub(replace_url, normalized_value)
            if not valid or "url(" in _CSS_URL_RE.sub("", normalized_value).lower():
                continue
            normalized_value = rewritten
            used_ids.update(declaration_ids)
        declarations.append(f"{normalized_name}:{normalized_value}")
    return ";".join(declarations)[:4000], used_ids


def _sanitize_captured_article(source: str, canonical_url: str) -> tuple[str, set[str]]:
    soup = BeautifulSoup(source, "html.parser")
    root = _select_article_root(soup, canonical_url)
    if root is None:
        raise WebArticleImportError("未能从浏览器采集内容中提取公众号正文")
    for tag in root.find_all(list(_DISCARDED_TAGS)):
        tag.decompose()

    fragment = BeautifulSoup("<section></section>", "html.parser")
    container = fragment.section
    assert container is not None
    for child in list(root.contents):
        container.append(child.extract())

    used_ids: set[str] = set()
    for tag in list(container.find_all(True)):
        name = tag.name.lower()
        if name in _DISCARDED_TAGS:
            tag.decompose()
            continue
        if name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue
        attributes: dict[str, str] = {}
        if tag.has_attr("style"):
            style, style_ids = _captured_style(str(tag.get("style") or ""))
            if style:
                attributes["style"] = style
                used_ids.update(style_ids)
        for attribute_name in ("align", "valign", "colspan", "rowspan", "width", "height"):
            attribute_value = str(tag.get(attribute_name) or "").strip()
            if attribute_value and len(attribute_value) <= 32:
                attributes[attribute_name] = attribute_value
        if tag.name == "a":
            href = _safe_link(str(tag.get("href") or ""), canonical_url)
            if href:
                attributes["href"] = href
        if tag.name == "img":
            captured = _CAPTURE_ASSET_URL_RE.fullmatch(str(tag.get("src") or "").strip())
            if captured is None:
                tag.decompose()
                continue
            asset_id = captured.group(1).lower()
            used_ids.add(asset_id)
            attributes["src"] = f"{_ASSET_URL_PREFIX}{asset_id}"
            alt = str(tag.get("alt") or "").strip()
            if alt:
                attributes["alt"] = alt[:512]
        tag.attrs = attributes

    rendered = str(container)
    plain = re.sub(r"\s+", " ", container.get_text(" ", strip=True)).strip()
    if not plain and not container.find("img"):
        raise WebArticleImportError("未能从浏览器采集内容中提取公众号正文")
    if len(rendered.encode("utf-8")) > get_settings().MAX_DOCUMENT_HTML_BYTES:
        raise WebArticleImportError("文章正文超过允许大小")
    return rendered, used_ids


def _image_source_from_tag(tag: Tag) -> str:
    return next((str(tag.get(name) or "").strip() for name in _IMAGE_SOURCE_ATTRIBUTES if tag.get(name)), "")


def _article_cover_source(source: str, canonical_url: str) -> str:
    """Return a safe candidate only; the source URL is never persisted."""
    soup = BeautifulSoup(source, "html.parser")
    candidates: list[str] = []
    if _is_wechat_article(canonical_url):
        for selector in ("#js_cover img", "img#js_cover", "#js_cover_image"):
            tag = soup.select_one(selector)
            if tag:
                candidates.append(_image_source_from_tag(tag))

    for tag in soup.find_all("meta"):
        key = str(tag.get("property") or tag.get("name") or "").strip().lower()
        if key in {"og:image", "twitter:image"}:
            candidates.append(str(tag.get("content") or ""))

    link = soup.select_one("link[rel='image_src']")
    if link:
        candidates.append(str(link.get("href") or ""))

    if _is_wechat_article(canonical_url):
        for script in soup.find_all("script"):
            match = re.search(r"\bmsg_cdn_url\s*=\s*(['\"])(.*?)\1", script.get_text() or "", re.DOTALL)
            if match:
                candidates.append(match.group(2))

    for raw_source in candidates:
        image_source = _safe_image_source(raw_source, canonical_url)
        if image_source:
            return image_source
    return ""


async def _capture_article_cover(source: str, canonical_url: str) -> tuple[CapturedAsset | None, list[str]]:
    cover_source = _article_cover_source(source, canonical_url)
    if not cover_source:
        return None, ["未能识别可导入的文章封面，请在公众号草稿中手动上传。"]

    timeout = httpx.Timeout(10.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        try:
            data, image = await fetch_public_image(client, cover_source, canonical_url)
        except PublicFetchError:
            return None, ["封面无法保存，请在公众号草稿中手动上传。"]
    if image.content_type not in _WECHAT_COVER_CONTENT_TYPES:
        return None, ["封面图片格式不受公众号支持，请在公众号草稿中手动上传。"]
    return (
        uuid4().hex,
        image.content_type,
        image.extension,
        data,
        image.width,
        image.height,
    ), []


async def _capture_article_images(html_template: str, canonical_url: str) -> tuple[str, list[CapturedAsset], int, int, list[str]]:
    soup = BeautifulSoup(html_template, "html.parser")
    image_tags = list(soup.find_all("img"))
    warnings: list[str] = []
    if len(image_tags) > MAX_ARTICLE_IMAGES:
        warnings.append(f"文章包含 {len(image_tags)} 张图片，仅下载前 {MAX_ARTICLE_IMAGES} 张，其余图片将保留原始外链。")
    candidates = image_tags[:MAX_ARTICLE_IMAGES]
    source_to_tags: dict[str, list[Tag]] = {}
    for tag in candidates:
        source = str(tag.get("src") or "").strip()
        if source:
            source_to_tags.setdefault(source, []).append(tag)

    semaphore = asyncio.Semaphore(IMAGE_FETCH_CONCURRENCY)
    timeout = httpx.Timeout(10.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        async def fetch_one(source: str):
            async with semaphore:
                try:
                    data, image = await fetch_public_image(client, source, canonical_url)
                    return source, data, image, None
                except PublicFetchError as exc:
                    return source, None, None, str(exc)

        results = await asyncio.gather(*(fetch_one(source) for source in source_to_tags))

    assets: list[CapturedAsset] = []
    imported_count = 0
    external_count = max(0, len(image_tags) - len(candidates))
    for source, data, image, error in results:
        tags = source_to_tags[source]
        if data is None or image is None:
            if source.lower().startswith("data:"):
                for tag in tags:
                    tag.decompose()
                warnings.append("一张内嵌图片无法安全保存，已从导入稿中移除。")
            else:
                external_count += len(tags)
                warnings.append(f"{len(tags)} 张图片无法保存，将保留原始外链：{error or '未知错误'}。")
            continue
        asset_id = uuid4().hex
        assets.append((asset_id, image.content_type, image.extension, data, image.width, image.height))
        for tag in tags:
            tag["src"] = f"{_ASSET_URL_PREFIX}{asset_id}"
        imported_count += len(tags)

    return str(soup), assets, imported_count, external_count, warnings


def _preview_html(import_session: WebArticleImport, preview_token: str) -> str:
    rendered = import_session.html_template
    for asset in import_session.assets:
        endpoint = _preview_asset_url(import_session, asset.asset_id, preview_token)
        rendered = rendered.replace(f"{_ASSET_URL_PREFIX}{asset.asset_id}", endpoint)
    return rendered


def _preview_asset_url(import_session: WebArticleImport, asset_id: str, preview_token: str) -> str:
    return (
        f"/api/documents/link-imports/{import_session.id}/assets/{asset_id}"
        f"?preview_token={quote(preview_token, safe='')}"
    )


def web_article_import_preview_payload(import_session: WebArticleImport, preview_token: str) -> dict:
    cover_preview_url = (
        _preview_asset_url(import_session, import_session.cover_asset_id, preview_token)
        if import_session.cover_asset_id
        else None
    )
    return {
        "id": import_session.id,
        "title": import_session.title,
        "preview_html": _preview_html(import_session, preview_token),
        "cover_preview_url": cover_preview_url,
        "cover_requires_crops": bool(import_session.cover_asset_id and import_session.cover_requires_crops),
        "image_count": import_session.image_count,
        "imported_image_count": import_session.imported_image_count,
        "external_image_count": import_session.external_image_count,
        "warnings": json.loads(import_session.warnings_json or "[]"),
        "expires_at": import_session.expires_at,
    }


async def create_web_article_import(raw_url: str, user_id: int, db: Session) -> tuple[WebArticleImport, str]:
    try:
        canonical_url, source = await fetch_public_html(raw_url)
        if is_wechat_verification_page(source, canonical_url):
            capture_url = resolve_wechat_capture_url(canonical_url, raw_url) or canonical_url
            raise WechatVerificationRequiredError(capture_url)
        title, html_template, warnings = _sanitize_article(source, canonical_url)
        cover_result, images_result = await asyncio.gather(
            _capture_article_cover(source, canonical_url),
            _capture_article_images(html_template, canonical_url),
        )
        cover_asset, cover_warnings = cover_result
        html_template, assets, imported_count, external_count, image_warnings = images_result
    except PublicFetchError as exc:
        raise WebArticleImportError(str(exc)) from exc
    if cover_asset is not None:
        assets.insert(0, cover_asset)
    warnings.extend(image_warnings)
    warnings.extend(cover_warnings)
    import_id = str(uuid4())
    preview_token = token_urlsafe(32)
    import_session = WebArticleImport(
        id=import_id,
        owner_id=user_id,
        title=title,
        html_template=html_template,
        warnings_json=json.dumps(warnings, ensure_ascii=False),
        image_count=len(BeautifulSoup(html_template, "html.parser").find_all("img")),
        imported_image_count=imported_count,
        external_image_count=external_count,
        cover_asset_id=cover_asset[0] if cover_asset else None,
        cover_requires_crops=bool(cover_asset and not _is_wechat_article(canonical_url)),
        preview_token_hash=hashlib.sha256(preview_token.encode("utf-8")).hexdigest(),
        expires_at=_utcnow() + WEB_ARTICLE_IMPORT_TTL,
    )
    db.add(import_session)
    for asset_id, content_type, extension, data, width, height in assets:
        db.add(
            WebArticleImportAsset(
                import_id=import_id,
                asset_id=asset_id,
                content_type=content_type,
                extension=extension,
                width=width,
                height=height,
                data=data,
            )
        )
    db.flush()
    db.refresh(import_session)
    return import_session, preview_token


def create_web_article_capture_session(raw_url: str, user_id: int, db: Session) -> tuple[LayoutCaptureSession, str]:
    try:
        return create_browser_capture_session(raw_url, user_id, CAPTURE_PURPOSE_WEB_ARTICLE_IMPORT, db)
    except BrowserCaptureError as exc:
        raise WebArticleImportError(str(exc)) from exc


def complete_captured_web_article_import(
    db: Session,
    capture_id: str,
    capture_token: str,
    captured_url: str,
    source_html: str,
    title: str,
    captured_assets: dict[str, tuple[bytes, local_uploads.ImageInfo]],
    omitted_asset_count: int = 0,
    cover_asset_id: str | None = None,
) -> tuple[WebArticleImport, str]:
    try:
        capture_session = load_browser_capture_session(
            db,
            capture_id,
            capture_token,
            captured_url,
            CAPTURE_PURPOSE_WEB_ARTICLE_IMPORT,
        )
    except BrowserCaptureExpiredError as exc:
        raise WebArticleImportExpiredError(str(exc)) from exc
    except BrowserCaptureError as exc:
        raise WebArticleImportError(str(exc)) from exc
    if len(source_html.encode("utf-8")) > MAX_CAPTURE_HTML_BYTES:
        raise WebArticleImportError("浏览器采集正文超过 5MB 限制")
    if len(captured_assets) > MAX_CAPTURE_ASSETS:
        raise WebArticleImportError(f"浏览器采集图片超过 {MAX_CAPTURE_ASSETS} 张限制")
    if any(len(data) > MAX_CAPTURE_IMAGE_BYTES for data, _ in captured_assets.values()):
        raise WebArticleImportError("浏览器采集图片超过 10MB 限制")
    if sum(len(data) for data, _ in captured_assets.values()) > MAX_CAPTURE_IMAGE_TOTAL_BYTES:
        raise WebArticleImportError("浏览器采集图片总大小超过 50MB 限制")

    html_template, body_asset_ids = _sanitize_captured_article(source_html, capture_session.canonical_url)
    normalized_cover_id = cover_asset_id.lower() if cover_asset_id else None
    expected_ids = set(body_asset_ids)
    if normalized_cover_id:
        expected_ids.add(normalized_cover_id)
    if expected_ids != set(captured_assets):
        raise WebArticleImportError("浏览器采集图片清单与正文或封面占位符不一致")

    warnings: list[str] = []
    if omitted_asset_count:
        warnings.append(f"有 {omitted_asset_count} 个正文图片素材未能由浏览器采集，已从导入内容中移除。")
    if normalized_cover_id:
        cover_image = captured_assets[normalized_cover_id][1]
        if cover_image.content_type not in _WECHAT_COVER_CONTENT_TYPES:
            warnings.append("文章封面格式不受公众号支持，请在公众号草稿中手动上传。")
            normalized_cover_id = None
    else:
        warnings.append("未能识别或保存文章封面，请在公众号草稿中手动上传。")

    active_ids = set(body_asset_ids)
    if normalized_cover_id:
        active_ids.add(normalized_cover_id)
    import_id = str(uuid4())
    preview_token = token_urlsafe(32)
    normalized_title = re.sub(r"\s+", " ", title).strip()[:256] or "未命名推文"
    image_count = len(BeautifulSoup(html_template, "html.parser").find_all("img"))
    import_session = WebArticleImport(
        id=import_id,
        owner_id=capture_session.user_id,
        title=normalized_title,
        html_template=html_template,
        warnings_json=json.dumps(warnings, ensure_ascii=False),
        image_count=image_count,
        imported_image_count=image_count,
        external_image_count=0,
        cover_asset_id=normalized_cover_id,
        cover_requires_crops=False,
        preview_token_hash=hashlib.sha256(preview_token.encode("utf-8")).hexdigest(),
        expires_at=_utcnow() + WEB_ARTICLE_IMPORT_TTL,
    )
    db.add(import_session)
    for asset_id in active_ids:
        data, image = captured_assets[asset_id]
        db.add(
            WebArticleImportAsset(
                import_id=import_id,
                asset_id=asset_id,
                content_type=image.content_type,
                extension=image.extension,
                width=image.width,
                height=image.height,
                data=data,
            )
        )
    complete_browser_capture_session(capture_session)
    db.flush()
    db.refresh(import_session)
    return import_session, preview_token


def _load_import(db: Session, import_id: str, user_id: int) -> WebArticleImport:
    import_session = (
        db.query(WebArticleImport)
        .options(selectinload(WebArticleImport.assets))
        .filter(WebArticleImport.id == import_id, WebArticleImport.owner_id == user_id)
        .one_or_none()
    )
    if import_session is None:
        raise WebArticleImportError("链接导入任务不存在")
    if _as_utc(import_session.expires_at) <= _utcnow():
        raise WebArticleImportExpiredError("链接导入预览已过期，请重新抓取文章")
    return import_session


def get_web_article_import_preview_asset(db: Session, import_id: str, asset_id: str, preview_token: str) -> WebArticleImportAsset:
    import_session = (
        db.query(WebArticleImport)
        .filter(
            WebArticleImport.id == import_id,
            WebArticleImport.status == WebArticleImportStatus.PENDING,
            WebArticleImport.expires_at > _utcnow(),
        )
        .one_or_none()
    )
    token_hash = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()
    if import_session is None or not import_session.preview_token_hash or not hmac.compare_digest(import_session.preview_token_hash, token_hash):
        raise WebArticleImportExpiredError("链接导入预览已过期或不可用")
    asset = (
        db.query(WebArticleImportAsset)
        .filter(WebArticleImportAsset.import_id == import_id, WebArticleImportAsset.asset_id == asset_id)
        .one_or_none()
    )
    if asset is None:
        raise WebArticleImportExpiredError("链接导入图片已过期或不可用")
    return asset


def _center_crop_value(width: int, height: int, aspect: float) -> str:
    if width <= 0 or height <= 0 or aspect <= 0:
        return ""
    source_aspect = width / height
    if source_aspect > aspect:
        crop_width = aspect / source_aspect
        x1, y1, x2, y2 = (1 - crop_width) / 2, 0.0, (1 + crop_width) / 2, 1.0
    else:
        crop_height = source_aspect / aspect
        x1, y1, x2, y2 = 0.0, (1 - crop_height) / 2, 1.0, (1 + crop_height) / 2

    def format_value(value: float) -> str:
        return f"{min(1.0, max(0.0, value)):.6f}".rstrip("0").rstrip(".") or "0"

    return "_".join(format_value(value) for value in (x1, y1, x2, y2))


def complete_web_article_import(import_id: str, current_user: User, db: Session) -> Document:
    import_session = _load_import(db, import_id, current_user.id)
    if import_session.status == WebArticleImportStatus.COMPLETED:
        document = db.get(Document, import_session.document_id)
        if document:
            return document
        raise WebArticleImportError("链接导入任务状态异常")
    if import_session.status != WebArticleImportStatus.PENDING:
        raise WebArticleImportError("链接导入任务不可用")

    urls: dict[str, str] = {}
    try:
        for asset in import_session.assets:
            urls[asset.asset_id] = store_document_image(db, asset.data, f"web-article-{asset.asset_id}.{asset.extension}")
    except DocumentImageStorageError as exc:
        raise WebArticleImportError(f"文章图片保存失败：{exc}") from exc
    html_content = import_session.html_template
    for asset_id, url in urls.items():
        html_content = html_content.replace(f"{_ASSET_URL_PREFIX}{asset_id}", html.escape(url, quote=True))
    if _ASSET_URL_PREFIX in html_content:
        raise WebArticleImportError("链接导入图片数据不完整，请重新抓取文章")
    validation = validate_html_structure(html_content)
    if not validation.valid:
        raise WebArticleImportError(f"解析后的正文结构无效：{validation.errors[0]}")

    cover_asset = next(
        (asset for asset in import_session.assets if asset.asset_id == import_session.cover_asset_id),
        None,
    )
    cover_url = urls.get(import_session.cover_asset_id or "", "")
    crop_235_1 = ""
    crop_1_1 = ""
    if cover_asset and cover_url and import_session.cover_requires_crops:
        crop_235_1 = _center_crop_value(cover_asset.width, cover_asset.height, 2.35)
        crop_1_1 = _center_crop_value(cover_asset.width, cover_asset.height, 1.0)

    document = Document(
        owner_id=current_user.id,
        created_by_id=current_user.id,
        last_modified_by_id=current_user.id,
        title=import_session.title[:256] or "未命名推文",
        current_html=html_content,
        source_type=DocumentSourceType.WEB,
        wechat_cover_url=cover_url,
        wechat_pic_crop_235_1=crop_235_1,
        wechat_pic_crop_1_1=crop_1_1,
    )
    db.add(document)
    db.flush()
    ensure_default_chat_session(db, document.id)
    create_document_version(db, document, current_user.id, DocumentVersionSource.INITIAL, "链接导入")
    import_session.status = WebArticleImportStatus.COMPLETED
    import_session.document_id = document.id
    import_session.assets.clear()
    db.commit()
    db.refresh(document)
    return document


def cancel_web_article_import(import_id: str, user_id: int, db: Session) -> None:
    import_session = _load_import(db, import_id, user_id)
    if import_session.status != WebArticleImportStatus.PENDING:
        raise WebArticleImportError("链接导入已完成，不能取消")
    db.delete(import_session)
    db.commit()


def cleanup_expired_web_article_imports(db: Session, now: datetime | None = None) -> int:
    expired_ids = [
        import_id
        for (import_id,) in db.query(WebArticleImport.id)
        .filter(WebArticleImport.expires_at <= (now or _utcnow()))
        .all()
    ]
    if not expired_ids:
        return 0
    db.query(WebArticleImportAsset).filter(WebArticleImportAsset.import_id.in_(expired_ids)).delete(synchronize_session=False)
    db.query(WebArticleImport).filter(WebArticleImport.id.in_(expired_ids)).delete(synchronize_session=False)
    db.commit()
    return len(expired_ids)
