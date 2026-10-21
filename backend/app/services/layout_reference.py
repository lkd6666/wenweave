"""Secure extraction and short-lived storage for external layout references."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import html
import ipaddress
import re
import socket
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from secrets import token_urlsafe
from typing import Iterable
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.chat_layout_reference import ChatLayoutReference, ChatLayoutReferenceAsset
from app.models.chat_session_layout_reference import ChatSessionLayoutReference
from app.models.layout_capture_session import LayoutCaptureSession
from app.services import local_uploads
from app.services.browser_capture import (
    CAPTURE_PURPOSE_LAYOUT_REFERENCE,
    BrowserCaptureError,
    BrowserCaptureExpiredError,
    MAX_CAPTURE_ASSETS,
    MAX_CAPTURE_HTML_BYTES,
    MAX_CAPTURE_IMAGE_BYTES,
    MAX_CAPTURE_IMAGE_TOTAL_BYTES,
    WechatVerificationRequiredError,
    cleanup_expired_browser_capture_sessions,
    complete_browser_capture_session,
    create_browser_capture_session,
    is_wechat_verification_page,
    load_browser_capture_session,
    normalize_wechat_article_url,
    resolve_wechat_capture_url,
)
from app.services.document_images import DocumentImageStorageError, store_document_image
from app.services.external_fetch import PublicFetchError, fetch_public_html, fetch_public_image
from app.services.css_declarations import split_css_declarations as _split_css_declarations


REFERENCE_TTL_SECONDS = 15 * 60
FETCH_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = MAX_CAPTURE_HTML_BYTES
MAX_REFERENCE_HTML_CHARS = 48_000
MAX_REFERENCE_IMAGES = MAX_CAPTURE_ASSETS
MAX_REFERENCE_IMAGE_BYTES = MAX_CAPTURE_IMAGE_BYTES
MAX_REFERENCE_IMAGE_TOTAL_BYTES = MAX_CAPTURE_IMAGE_TOTAL_BYTES
REFERENCE_IMAGE_FETCH_CONCURRENCY = 4
_WECHAT_HOST = "mp.weixin.qq.com"
_WECHAT_COMPAT_PROXY_HOSTS = {
    _WECHAT_HOST,
    "mmbiz.qpic.cn",
    "mmecoa.qpic.cn",
    "res.wx.qq.com",
    "wx.qlogo.cn",
}
_WECHAT_COMPAT_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_ALLOWED_TAGS = {
    "article", "section", "div", "p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s",
    "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "br", "hr", "pre", "code",
    "figure", "figcaption", "small", "sup", "sub", "a",
}
_SVG_TAGS = {
    "svg", "g", "path", "circle", "ellipse", "line", "polyline", "polygon", "rect", "text", "tspan", "title", "desc",
    "defs", "clippath", "mask", "lineargradient", "radialgradient", "stop", "use", "image", "filter", "feflood", "feblend",
    "fegaussianblur", "feoffset", "fecolormatrix", "fecomponenttransfer", "fefuncr", "fefuncg", "fefuncb", "fefunca",
    "fecomposite", "femerge", "femergenode", "fedropshadow",
}
_SVG_OUTPUT_TAG_NAMES = {
    "clippath": "clipPath",
    "lineargradient": "linearGradient",
    "radialgradient": "radialGradient",
    "feflood": "feFlood",
    "feblend": "feBlend",
    "fegaussianblur": "feGaussianBlur",
    "feoffset": "feOffset",
    "fecolormatrix": "feColorMatrix",
    "fecomponenttransfer": "feComponentTransfer",
    "fefuncr": "feFuncR",
    "fefuncg": "feFuncG",
    "fefuncb": "feFuncB",
    "fefunca": "feFuncA",
    "fecomposite": "feComposite",
    "femerge": "feMerge",
    "femergenode": "feMergeNode",
    "fedropshadow": "feDropShadow",
}
_ALLOWED_TAGS.update(_SVG_TAGS)
_ALLOWED_ATTRIBUTES = {
    "style", "class", "id", "align", "width", "height", "colspan", "rowspan", "valign", "alt", "role", "aria-label",
    "data-w", "data-ratio", "data-mode", "data-ignore-width", "data-no-dark", "data-ignore-dm",
    "xmlns", "viewbox", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "d", "points",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap", "stroke-linejoin",
    "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "transform", "transform-origin", "opacity", "preserveaspectratio",
    "text-anchor", "dominant-baseline", "font-size", "font-family", "font-weight", "offset", "stop-color", "stop-opacity",
    "gradientunits", "gradienttransform", "spreadmethod", "clip-path", "clip-rule", "mask", "maskunits", "maskcontentunits",
    "filter", "filterunits", "primitiveunits", "color-interpolation-filters", "in", "in2", "result", "stddeviation", "dx", "dy",
    "operator", "k1", "k2", "k3", "k4", "mode", "type", "values", "slope", "intercept", "tablevalues", "flood-color",
    "flood-opacity", "focusable", "href", "xlink:href",
}
_BASE_ALLOWED_ATTRIBUTES = {
    "style", "class", "id", "align", "width", "height", "colspan", "rowspan", "valign", "alt", "role", "aria-label",
    "data-w", "data-ratio", "data-mode", "data-ignore-width", "data-no-dark", "data-ignore-dm",
}
_SVG_ONLY_ATTRIBUTES = _ALLOWED_ATTRIBUTES - _BASE_ALLOWED_ATTRIBUTES
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li", "figure", "table", "section"}
_DISCARDED_TAGS = {
    "script", "style", "iframe", "object", "embed", "template", "noscript", "canvas", "form", "button", "input",
    "foreignobject", "animate", "animatetransform", "animatemotion", "set",
}
_DANGEROUS_STYLE = re.compile(r"(?:expression\s*\(|@import|behavior\s*:|-moz-binding)", re.IGNORECASE)
_ASSET_URL_RE = re.compile(r"^layout-reference://([a-f0-9]{32})$", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<url>.*?)(?P=quote)\s*\)", re.IGNORECASE | re.DOTALL)
_DATA_IMAGE_URL_RE = re.compile(
    r"^data:image/(?:png|jpeg|jpg|gif|webp|avif|bmp);base64,([a-z0-9+/=\s]+)$", re.IGNORECASE
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_IMAGE_SOURCE_ATTRIBUTES = ("data-src", "data-original", "data-actualsrc", "src")
_CAPTURE_ASSET_URL_RE = re.compile(r"^layout-capture://([a-f0-9]{32})$", re.IGNORECASE)
_SAFE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,255}$")
_SVG_LOCAL_URL_ATTRIBUTES = {"fill", "stroke", "filter", "clip-path", "mask"}


class LayoutReferenceError(ValueError):
    pass


class LayoutReferenceExpiredError(LayoutReferenceError):
    pass


@dataclass
class _AssetSource:
    asset_id: str
    source: str
    usage_count: int = 0
    background_uses: int = 0
    positioned_uses: int = 0
    content_image_uses: int = 0
    hint_text: str = ""

    def record_use(self, kind: str, *, positioned: bool, content_image: bool, hint: str) -> None:
        self.usage_count += 1
        self.background_uses += int(kind == "background")
        self.positioned_uses += int(positioned)
        self.content_image_uses += int(content_image)
        if hint and len(self.hint_text) < 400:
            self.hint_text = f"{self.hint_text} {hint}".strip()[:400]


@dataclass(frozen=True)
class LayoutReferenceAsset:
    asset_id: str
    object_key: str
    content_type: str
    extension: str
    width: int = 0
    height: int = 0
    usage_count: int = 0
    role: str = "正文图片"
    default_selected: bool = False
    data: bytes | None = field(default=None, repr=False, compare=False)


@dataclass
class LayoutReference:
    reference_id: str
    user_id: int
    canonical_url: str
    title: str
    site_name: str
    html_template: str
    block_count: int
    image_slots: int
    extracted_from: str
    warning: str | None
    expires_at: float
    preview_token: str
    assets: list[LayoutReferenceAsset] = field(default_factory=list)

    @property
    def html(self) -> str:
        """Compatibility accessor for callers that only need structural HTML."""
        return self.html_template

    def _render(self, urls: dict[str, str]) -> str:
        rendered = self.html_template
        for asset_id, url in urls.items():
            rendered = rendered.replace(f"layout-reference://{asset_id}", html.escape(url, quote=True))
        return rendered

    def selected_assets(self, selected_asset_ids: Iterable[str]) -> list[LayoutReferenceAsset]:
        selected = {str(asset_id) for asset_id in selected_asset_ids}
        available = {asset.asset_id for asset in self.assets}
        invalid = selected - available
        if invalid:
            raise LayoutReferenceError("所选参考图片已失效，请重新解析链接")
        return [asset for asset in self.assets if asset.asset_id in selected]

    def default_selected_asset_ids(self) -> list[str]:
        return [asset.asset_id for asset in self.assets if asset.default_selected]

    @staticmethod
    def _remove_unselected_assets(template: str, selected_ids: set[str]) -> str:
        """Drop body photos rather than leaving empty image slots in the template."""
        available = set(re.findall(r"layout-reference://([a-f0-9]{32})", template, flags=re.IGNORECASE))
        for asset_id in available - selected_ids:
            escaped = re.escape(asset_id)
            template = re.sub(
                rf"<img\b[^>]*\bsrc=\"layout-reference://{escaped}\"[^>]*>",
                "",
                template,
                flags=re.IGNORECASE,
            )
            template = re.sub(
                rf'<image\b[^>]*\bhref="layout-reference://{escaped}"[^>]*>\s*</image>',
                "",
                template,
                flags=re.IGNORECASE,
            )

        def remove_unselected_style_assets(match: re.Match[str]) -> str:
            quote_char = match.group("quote")
            style = html.unescape(match.group("value"))
            declarations: list[str] = []
            for declaration in _split_css_declarations(style):
                property_name, separator, property_value = declaration.partition(":")
                if not separator:
                    continue
                asset_ids = {
                    item.lower()
                    for item in re.findall(
                        r"layout-reference://([a-f0-9]{32})",
                        property_value,
                        flags=re.IGNORECASE,
                    )
                }
                unselected_ids = asset_ids - selected_ids
                if not unselected_ids:
                    declarations.append(declaration)
                    continue
                # A declaration that only refers to omitted assets is useless.
                # For a multi-layer background retain selected layers by replacing
                # omitted URL layers with CSS `none`.
                if not asset_ids - unselected_ids:
                    continue

                def remove_url_layer(url_match: re.Match[str]) -> str:
                    asset_match = _ASSET_URL_RE.fullmatch(url_match.group("url").strip())
                    if asset_match and asset_match.group(1).lower() in unselected_ids:
                        return "none"
                    return url_match.group(0)

                declarations.append(
                    f"{property_name}:{_CSS_URL_RE.sub(remove_url_layer, property_value)}"
                )
            cleaned = ";".join(part.strip() for part in declarations if part.strip())
            if not cleaned:
                return ""
            return f"style={quote_char}{html.escape(cleaned, quote=True)}{quote_char}"

        template = re.sub(
            r"style\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
            remove_unselected_style_assets,
            template,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Empty styled elements can be author decorations, grid cells or spacing.
        # Only clear empty unstyled wrappers left after photo removal.
        empty_element = re.compile(r"<(figure|p|div|span|section)\b[^>]*>\s*</\1>", re.IGNORECASE)
        previous = ""
        while previous != template:
            def remove_empty_element(match: re.Match[str]) -> str:
                opening_tag = match.group(0).split(">", 1)[0]
                return match.group(0) if re.search(r"\bstyle\s*=", opening_tag, re.IGNORECASE) else ""

            previous, template = template, empty_element.sub(remove_empty_element, template)
        return template

    def materialized_template(self, urls: dict[str, str], selected_asset_ids: Iterable[str]) -> str:
        selected = {str(asset_id) for asset_id in selected_asset_ids}
        cleaned = self._remove_unselected_assets(self.html_template, selected)
        rendered = cleaned
        for asset_id, url in urls.items():
            if asset_id in selected:
                rendered = rendered.replace(f"layout-reference://{asset_id}", html.escape(url, quote=True))
        return re.sub(
            r"\sdata-layout-reference-asset=(['\"])[a-f0-9]{32}\1",
            "",
            rendered,
            flags=re.IGNORECASE,
        )

    def preview_payload(self) -> dict:
        urls = {
            asset.asset_id: (
                f"/api/layout-references/{self.reference_id}/assets/{asset.asset_id}"
                f"?preview_token={quote(self.preview_token, safe='')}"
            )
            for asset in self.assets
        }
        return {
            "reference_id": self.reference_id,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "site_name": self.site_name,
            "preview_html": self._render(urls),
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "preview_url": urls[asset.asset_id],
                    "content_type": asset.content_type,
                    "width": asset.width,
                    "height": asset.height,
                    "usage_count": asset.usage_count,
                    "role": asset.role,
                    "default_selected": asset.default_selected,
                }
                for asset in self.assets
            ],
            "summary": {
                "block_count": self.block_count,
                "image_slots": self.image_slots,
                "image_assets": len(self.assets),
                "extracted_from": self.extracted_from,
            },
            "requires_asset_reuse_confirmation": bool(self.default_selected_asset_ids()),
            "warning": self.warning,
        }

    def agent_payload(self, urls: dict[str, str], selected_asset_ids: Iterable[str]) -> dict:
        return {
            "title": self.title,
            "site_name": self.site_name,
            "html": self.materialized_template(urls, selected_asset_ids),
            "block_count": self.block_count,
            "image_slots": self.image_slots,
            "image_assets": len({str(asset_id) for asset_id in selected_asset_ids}),
            "extracted_from": self.extracted_from,
        }

    def cleanup(self) -> None:
        # Reference assets are persisted with their TTL-bound database record.
        # There is no process-local file to delete here.
        return None


class _ReferenceCache:
    def __init__(self, *, max_entries: int | None = None, max_bytes: int | None = None) -> None:
        settings = get_settings()
        self.max_entries = max(1, int(max_entries or settings.LAYOUT_REFERENCE_CACHE_MAX_ENTRIES))
        self.max_bytes = max(1024 * 1024, int(max_bytes or settings.LAYOUT_REFERENCE_CACHE_MAX_BYTES))
        self._items: OrderedDict[str, LayoutReference] = OrderedDict()

    @staticmethod
    def _entry_bytes(item: LayoutReference) -> int:
        text_bytes = sum(
            len(str(value or "").encode("utf-8"))
            for value in (
                item.canonical_url,
                item.title,
                item.site_name,
                item.html_template,
                item.extracted_from,
                item.warning,
                item.preview_token,
            )
        )
        asset_bytes = sum(
            len(asset.data or b"")
            + len(asset.object_key.encode("utf-8"))
            + len(asset.content_type.encode("utf-8"))
            + len(asset.role.encode("utf-8"))
            + 128
            for asset in item.assets
        )
        return text_bytes + asset_bytes + 512

    def _total_bytes(self) -> int:
        return sum(self._entry_bytes(item) for item in self._items.values())

    def _enforce_limits(self) -> None:
        while self._items and (
            len(self._items) > self.max_entries or self._total_bytes() > self.max_bytes
        ):
            _reference_id, item = self._items.popitem(last=False)
            item.cleanup()

    def purge(self) -> None:
        now = time.monotonic()
        for reference_id, item in list(self._items.items()):
            if item.expires_at <= now:
                self._items.pop(reference_id, None)

    def put(self, item: LayoutReference) -> None:
        self.purge()
        self._items.pop(item.reference_id, None)
        self._items[item.reference_id] = item
        self._enforce_limits()

    def get(self, reference_id: str, user_id: int) -> LayoutReference:
        self.purge()
        item = self._items.get(reference_id)
        if not item or item.user_id != user_id:
            raise LayoutReferenceExpiredError("参考排版已过期或不可用，请重新解析链接")
        self._items.move_to_end(reference_id)
        return item

    def get_preview_asset(self, reference_id: str, asset_id: str, preview_token: str) -> LayoutReferenceAsset:
        self.purge()
        item = self._items.get(reference_id)
        if not item or not hmac.compare_digest(item.preview_token, preview_token):
            raise LayoutReferenceExpiredError("参考图片已过期或不可用，请重新解析链接")
        self._items.move_to_end(reference_id)
        for asset in item.assets:
            if hmac.compare_digest(asset.asset_id, asset_id):
                return asset
        raise LayoutReferenceExpiredError("参考图片已过期或不可用，请重新解析链接")


layout_reference_cache = _ReferenceCache()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive values for DateTime(timezone=True); MySQL drivers
    # may do the same depending on server configuration.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _expiry_from_monotonic(expires_at: float) -> datetime:
    return _utcnow() + timedelta(seconds=max(0.0, expires_at - time.monotonic()))


def _reference_from_record(
    record: ChatLayoutReference,
    assets: list[ChatLayoutReferenceAsset],
) -> LayoutReference:
    seconds_remaining = max(0.0, (_as_utc(record.expires_at) - _utcnow()).total_seconds())
    return LayoutReference(
        reference_id=record.reference_id,
        user_id=record.user_id,
        canonical_url=record.canonical_url,
        title=record.title,
        site_name=record.site_name,
        html_template=record.html_template,
        block_count=record.block_count,
        image_slots=record.image_slots,
        extracted_from=record.extracted_from,
        warning=record.warning,
        expires_at=time.monotonic() + seconds_remaining,
        # Capability validation happens against the persisted hash. A record
        # loaded by another worker must never be able to mint a new URL.
        preview_token=(
            decrypt_secret(record.preview_token_encrypted)
            if getattr(record, "preview_token_encrypted", "")
            else ""
        ),
        assets=[
            LayoutReferenceAsset(
                asset_id=asset.asset_id,
                object_key="",
                content_type=asset.content_type,
                extension=asset.extension,
                width=asset.width,
                height=asset.height,
                usage_count=asset.usage_count,
                role=asset.role,
                default_selected=asset.default_selected,
                data=asset.data,
            )
            for asset in assets
        ],
    )


def _load_persisted_layout_reference(db: Session, reference_id: str, user_id: int) -> LayoutReference:
    record = (
        db.query(ChatLayoutReference)
        .filter(
            ChatLayoutReference.reference_id == reference_id,
            ChatLayoutReference.user_id == user_id,
            ChatLayoutReference.expires_at > _utcnow(),
        )
        .one_or_none()
    )
    if record is None:
        raise LayoutReferenceExpiredError("参考排版已过期或不可用，请重新解析链接")
    assets = (
        db.query(ChatLayoutReferenceAsset)
        .filter(ChatLayoutReferenceAsset.reference_id == reference_id)
        .order_by(ChatLayoutReferenceAsset.id)
        .all()
    )
    reference = _reference_from_record(record, assets)
    layout_reference_cache.put(reference)
    return reference


def get_layout_reference(db: Session, reference_id: str, user_id: int) -> LayoutReference:
    try:
        return layout_reference_cache.get(reference_id, user_id)
    except LayoutReferenceExpiredError:
        return _load_persisted_layout_reference(db, reference_id, user_id)


def get_layout_reference_preview_asset(
    db: Session,
    reference_id: str,
    asset_id: str,
    preview_token: str,
) -> LayoutReferenceAsset:
    record = (
        db.query(ChatLayoutReference)
        .filter(
            ChatLayoutReference.reference_id == reference_id,
            ChatLayoutReference.expires_at > _utcnow(),
        )
        .one_or_none()
    )
    token_hash = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()
    if record is None or not hmac.compare_digest(record.preview_token_hash, token_hash):
        raise LayoutReferenceExpiredError("参考图片已过期或不可用，请重新解析链接")
    asset = (
        db.query(ChatLayoutReferenceAsset)
        .filter(
            ChatLayoutReferenceAsset.reference_id == reference_id,
            ChatLayoutReferenceAsset.asset_id == asset_id,
        )
        .one_or_none()
    )
    if asset is None:
        raise LayoutReferenceExpiredError("参考图片已过期或不可用，请重新解析链接")
    return LayoutReferenceAsset(
        asset_id=asset.asset_id,
        object_key="",
        content_type=asset.content_type,
        extension=asset.extension,
        width=asset.width,
        height=asset.height,
        usage_count=asset.usage_count,
        role=asset.role,
        default_selected=asset.default_selected,
        data=asset.data,
    )


def cleanup_expired_layout_references(db: Session, now: datetime | None = None) -> int:
    """Delete only expired temporary references; active previews survive restarts."""
    expired_ids = [
        reference_id
        for (reference_id,) in db.query(ChatLayoutReference.reference_id)
        .filter(ChatLayoutReference.expires_at <= (now or _utcnow()))
        .order_by(ChatLayoutReference.expires_at, ChatLayoutReference.reference_id)
        .limit(500)
        .all()
    ]
    if not expired_ids:
        return 0
    db.query(ChatLayoutReferenceAsset).filter(ChatLayoutReferenceAsset.reference_id.in_(expired_ids)).delete(
        synchronize_session=False
    )
    db.query(ChatLayoutReference).filter(ChatLayoutReference.reference_id.in_(expired_ids)).delete(
        synchronize_session=False
    )
    db.commit()
    return len(expired_ids)


def cleanup_expired_layout_capture_sessions(db: Session, now: datetime | None = None) -> int:
    return cleanup_expired_browser_capture_sessions(db, now)


def _normalise_url(raw_url: str) -> str:
    value = raw_url.strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise LayoutReferenceError("链接格式无效") from exc
    if parsed.scheme.lower() != "https":
        raise LayoutReferenceError("仅支持公开 HTTPS 链接")
    if not parsed.hostname or parsed.username or parsed.password:
        raise LayoutReferenceError("链接必须包含有效域名，且不能包含账号信息")
    try:
        port = parsed.port
    except ValueError as exc:
        raise LayoutReferenceError("链接端口无效") from exc
    if port not in {None, 443}:
        raise LayoutReferenceError("仅支持标准 HTTPS 端口")
    host = parsed.hostname.lower().rstrip(".")
    if not host:
        raise LayoutReferenceError("链接域名无效")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise LayoutReferenceError("不允许访问本机或内网地址")
    path = parsed.path or "/"
    return urlunsplit(("https", host, path, parsed.query, ""))


def _wechat_article_url(raw_url: str) -> str | None:
    return normalize_wechat_article_url(raw_url)


def _wechat_verification_target_url(verification_url: str, requested_url: str = "") -> str | None:
    return resolve_wechat_capture_url(verification_url, requested_url)


def _is_wechat_verification_page(source: str, canonical_url: str) -> bool:
    return is_wechat_verification_page(source, canonical_url)


async def _ensure_public_host(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise LayoutReferenceError("链接域名无效")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not literal_ip.is_global:
            raise LayoutReferenceError("不允许访问本机或内网地址")
        return
    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise LayoutReferenceError("无法解析参考链接的域名") from exc
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise LayoutReferenceError("无法解析参考链接的域名")
    for address in addresses:
        if not _is_allowed_resolved_address(host, address):
            raise LayoutReferenceError("参考链接指向了不允许访问的网络地址")


def _is_allowed_resolved_address(host: str, address: str) -> bool:
    """Allow the desktop environment's official WeChat proxy hosts narrowly."""
    try:
        parsed_address = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed_address.is_global:
        return True
    return host.lower().rstrip(".") in _WECHAT_COMPAT_PROXY_HOSTS and parsed_address in _WECHAT_COMPAT_PROXY_NETWORK


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }


async def _fetch_html(raw_url: str) -> tuple[str, str]:
    try:
        return await fetch_public_html(raw_url)
    except PublicFetchError as exc:
        raise LayoutReferenceError(str(exc)) from exc


def _safe_style(value: str, *, preserve_authored: bool = False) -> str:
    clean = value.strip()
    if not clean or _DANGEROUS_STYLE.search(clean):
        return ""
    declarations: list[str] = []
    for declaration in _split_css_declarations(clean):
        property_name, separator, property_value = declaration.partition(":")
        if not separator:
            continue
        normalized_name = property_name.strip().lower()
        normalized_value = property_value.strip().lower().replace("!important", "").strip()
        if "url(" in normalized_value:
            matches = list(_CSS_URL_RE.finditer(property_value))
            if not matches or any(
                not _ASSET_URL_RE.fullmatch(match.group("url").strip())
                and not (match.group("url").strip().startswith("#") and _SAFE_ID_RE.fullmatch(match.group("url").strip()[1:]))
                for match in matches
            ):
                return ""
        if not preserve_authored and normalized_name == "display" and normalized_value == "none":
            continue
        if not preserve_authored and normalized_name == "visibility" and normalized_value in {"hidden", "collapse"}:
            continue
        if not preserve_authored and normalized_name == "opacity":
            try:
                if float(normalized_value) <= 0:
                    continue
            except ValueError:
                pass
        if not preserve_authored and normalized_name == "content-visibility" and normalized_value == "hidden":
            continue
        declarations.append(f"{property_name.strip()}:{property_value.strip()}")
    rendered = ";".join(declarations)
    return rendered if preserve_authored else rendered[:4000]


def _safe_attributes(attrs: Iterable[tuple[str, str | None]], *, svg: bool = False, preserve_authored: bool = False) -> str:
    values: list[str] = []
    for name, value in attrs:
        normalized = name.lower()
        if value is None:
            continue
        if normalized in {"src", "data-layout-reference-asset"}:
            if normalized == "src" and _ASSET_URL_RE.fullmatch(value.strip()):
                values.append(f' src="{html.escape(value, quote=True)}"')
            elif normalized == "data-layout-reference-asset" and re.fullmatch(r"[a-f0-9]{32}", value, re.IGNORECASE):
                values.append(f' data-layout-reference-asset="{html.escape(value, quote=True)}"')
            continue
        if normalized not in _ALLOWED_ATTRIBUTES:
            continue
        if normalized in _SVG_ONLY_ATTRIBUTES and not svg:
            continue
        if normalized in {"href", "xlink:href"}:
            if not svg or not value.startswith("#") or not _SAFE_ID_RE.fullmatch(value[1:]):
                continue
        if normalized == "id" and not _SAFE_ID_RE.fullmatch(value):
            continue
        if normalized in _SVG_LOCAL_URL_ATTRIBUTES and "url(" in value.lower():
            if not re.fullmatch(r"url\(\s*#[A-Za-z_][A-Za-z0-9_.:-]{0,255}\s*\)", value, flags=re.IGNORECASE):
                continue
        if normalized == "style":
            value = _safe_style(value, preserve_authored=preserve_authored)
            if not value:
                continue
        safe_value = value if preserve_authored else value[:4000]
        values.append(f' {normalized}="{html.escape(safe_value, quote=True)}"')
    return "".join(values)


class _SanitisingCaptureParser(HTMLParser):
    def __init__(self, target: str, *, preserve_authored: bool = False) -> None:
        super().__init__(convert_charrefs=False)
        self.target = target
        self.preserve_authored = preserve_authored
        self.capture_depth = 0
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.discard_depth = 0
        self.block_count = 0
        self.image_slots = 0
        self.found = False
        self._asset_by_source: dict[str, str] = {}
        self.asset_sources: list[_AssetSource] = []

    @staticmethod
    def _matches_target(tag: str, attrs: list[tuple[str, str | None]], target: str) -> bool:
        attr_values = {name.lower(): value or "" for name, value in attrs}
        if target == "wechat":
            return attr_values.get("id") == "js_content"
        return tag == target

    @staticmethod
    def _style_is_positioned(value: str) -> bool:
        normalized = re.sub(r"\s+", "", value.lower())
        return bool(
            re.search(r"position:(?:absolute|fixed)", normalized)
            or ("z-index:" in normalized and "z-index:auto" not in normalized)
        )

    def _register_asset(
        self,
        raw_source: str,
        *,
        kind: str,
        attrs: Iterable[tuple[str, str | None]] = (),
    ) -> str:
        source = html.unescape(raw_source).strip()
        if not source:
            raise LayoutReferenceError("参考图片缺少可访问地址")
        self.image_slots += 1
        if not self.preserve_authored and self.image_slots > MAX_REFERENCE_IMAGES:
            raise LayoutReferenceError(f"参考页面图片超过 {MAX_REFERENCE_IMAGES} 张，无法完整保留")
        attr_values = {name.lower(): value or "" for name, value in attrs}
        style = attr_values.get("style", "")
        hint = " ".join((attr_values.get("class", ""), attr_values.get("alt", "")))
        parent = self.open_tags[-1] if self.open_tags else ""
        positioned = self._style_is_positioned(style)
        content_image = kind == "img" and parent in {"p", "figure", "li"} and not positioned
        asset_id = self._asset_by_source.get(source)
        if asset_id:
            next(item for item in self.asset_sources if item.asset_id == asset_id).record_use(
                kind,
                positioned=positioned,
                content_image=content_image,
                hint=hint,
            )
            return asset_id
        if len(self.asset_sources) >= MAX_REFERENCE_IMAGES:
            raise LayoutReferenceError(f"参考页面图片超过 {MAX_REFERENCE_IMAGES} 张，无法完整保留")
        asset_id = uuid4().hex
        self._asset_by_source[source] = asset_id
        asset = _AssetSource(asset_id=asset_id, source=source)
        asset.record_use(kind, positioned=positioned, content_image=content_image, hint=hint)
        self.asset_sources.append(asset)
        return asset_id

    def _rewrite_background_assets(self, value: str, attrs: Iterable[tuple[str, str | None]]) -> str:
        declarations: list[str] = []
        for declaration in _split_css_declarations(value):
            property_name, separator, property_value = declaration.partition(":")
            if not separator:
                declarations.append(declaration)
                continue
            if "url(" not in property_value.lower():
                declarations.append(declaration)
                continue

            def replace_url(match: re.Match[str]) -> str:
                source = match.group("url").strip()
                if source.startswith("#") and _SAFE_ID_RE.fullmatch(source[1:]):
                    return f"url({source})"
                asset_id = self._register_asset(source, kind="background", attrs=attrs)
                return f'url("layout-reference://{asset_id}")'

            rewritten, count = _CSS_URL_RE.subn(replace_url, property_value)
            if "url(" in property_value.lower() and not count:
                raise LayoutReferenceError("参考背景图片地址无法解析")
            declarations.append(f"{property_name}:{rewritten}")
        return ";".join(declarations)

    def _sanitised_attributes(self, tag: str, attrs: Iterable[tuple[str, str | None]]) -> str:
        values_source = list(attrs)
        values: list[tuple[str, str | None]] = []
        for name, value in values_source:
            if name.lower() == "style" and value is not None:
                values.append((name, self._rewrite_background_assets(value, values_source)))
            else:
                values.append((name, value))
        return _safe_attributes(values, svg=tag in _SVG_TAGS, preserve_authored=self.preserve_authored)

    def _append_open_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "image" and "svg" in self.open_tags:
            attr_values = {name.lower(): value or "" for name, value in attrs}
            source = attr_values.get("href") or attr_values.get("xlink:href")
            if source:
                asset_id = self._register_asset(source, kind="img", attrs=attrs)
                safe_attrs = self._sanitised_attributes(tag, [(name, value) for name, value in attrs if name.lower() not in {"href", "xlink:href"}])
                self.output.append(f'<image href="layout-reference://{asset_id}"{safe_attrs}>')
                self.open_tags.append(tag)
            return
        if tag == "img":
            attr_values = {name.lower(): value or "" for name, value in attrs}
            source = next((attr_values[name] for name in _IMAGE_SOURCE_ATTRIBUTES if attr_values.get(name, "").strip()), "")
            asset_id = self._register_asset(source, kind="img", attrs=attrs)
            safe_attrs = self._sanitised_attributes(tag, attrs)
            self.output.append(
                f'<img src="layout-reference://{asset_id}" data-layout-reference-asset="{asset_id}"{safe_attrs}>'
            )
            return
        if tag not in _ALLOWED_TAGS:
            return
        if tag in _BLOCK_TAGS:
            self.block_count += 1
        output_tag = _SVG_OUTPUT_TAG_NAMES.get(tag, tag)
        self.output.append(f"<{output_tag}{self._sanitised_attributes(tag, attrs)}>")
        if tag not in _VOID_TAGS:
            self.open_tags.append(tag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if not self.capture_depth:
            if not self._matches_target(normalized, attrs, self.target):
                return
            self.found = True
            self.capture_depth = 1
            self._append_open_tag(normalized, attrs)
            return
        if self.discard_depth:
            if normalized not in _VOID_TAGS:
                self.discard_depth += 1
            return
        if normalized in _DISCARDED_TAGS:
            if normalized not in _VOID_TAGS:
                self.discard_depth = 1
            return
        if normalized not in _VOID_TAGS:
            self.capture_depth += 1
        self._append_open_tag(normalized, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.capture_depth:
            normalized = tag.lower()
            previous_depth = len(self.open_tags)
            self._append_open_tag(normalized, attrs)
            if len(self.open_tags) > previous_depth and self.open_tags[-1] == normalized:
                self.open_tags.pop()
                self.output.append(f"</{_SVG_OUTPUT_TAG_NAMES.get(normalized, normalized)}>")

    def handle_endtag(self, tag: str) -> None:
        if not self.capture_depth:
            return
        normalized = tag.lower()
        if self.discard_depth:
            if normalized not in _VOID_TAGS:
                self.discard_depth -= 1
            return
        if normalized in _ALLOWED_TAGS and normalized != "img" and normalized in self.open_tags:
            while self.open_tags:
                open_tag = self.open_tags.pop()
                self.output.append(f"</{_SVG_OUTPUT_TAG_NAMES.get(open_tag, open_tag)}>")
                if open_tag == normalized:
                    break
        if normalized not in _VOID_TAGS:
            self.capture_depth -= 1
            if self.capture_depth <= 0:
                self.capture_depth = 0

    def handle_data(self, data: str) -> None:
        if self.capture_depth and not self.discard_depth:
            self.output.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if self.capture_depth and not self.discard_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.capture_depth and not self.discard_depth:
            self.output.append(f"&#{name};")

    def close_result(self) -> tuple[str, int, int, list[_AssetSource]]:
        self.close()
        while self.open_tags:
            tag = self.open_tags.pop()
            self.output.append(f"</{_SVG_OUTPUT_TAG_NAMES.get(tag, tag)}>")
        return "".join(self.output), self.block_count, self.image_slots, self.asset_sources


class _HtmlTruncator(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=False)
        self.limit = limit
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.length = 0
        self.truncated = False

    def _append(self, value: str) -> bool:
        if self.truncated:
            return False
        if self.length + len(value) > self.limit:
            remaining = max(0, self.limit - self.length)
            if remaining:
                self.output.append(value[:remaining])
                self.length += remaining
            self.truncated = True
            return False
        self.output.append(value)
        self.length += len(value)
        return True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.truncated:
            return
        normalized = tag.lower()
        output_tag = _SVG_OUTPUT_TAG_NAMES.get(normalized, normalized)
        value = f"<{output_tag}{_safe_attributes(attrs, svg=normalized in _SVG_TAGS)}>"
        if self._append(value) and tag not in _VOID_TAGS:
            self.open_tags.append(normalized)

    def handle_endtag(self, tag: str) -> None:
        if self.truncated:
            return
        normalized = tag.lower()
        if normalized in self.open_tags:
            while self.open_tags:
                open_tag = self.open_tags.pop()
                self._append(f"</{_SVG_OUTPUT_TAG_NAMES.get(open_tag, open_tag)}>")
                if open_tag == normalized:
                    break

    def handle_data(self, data: str) -> None:
        self._append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        self._append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append(f"&#{name};")

    def result(self) -> tuple[str, bool]:
        self.close()
        if self.truncated:
            self.output.append("<p>（参考排版内容已截断）</p>")
        while self.open_tags:
            tag = self.open_tags.pop()
            self.output.append(f"</{_SVG_OUTPUT_TAG_NAMES.get(tag, tag)}>")
        return "".join(self.output), self.truncated


class _PageTitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_title = ""
        self.title_text = ""
        self.heading_text = ""
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "meta" and not self.meta_title:
            marker = values.get("property", values.get("name", "")).lower()
            if marker in {"og:title", "twitter:title"}:
                self.meta_title = values.get("content", "")
        elif tag.lower() == "title":
            self._capture = "title"
        elif tag.lower() in {"h1", "h2"} and values.get("id") in {"activity-name", "js_name"}:
            self._capture = "heading"

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title" and self._capture == "title":
            self._capture = None
        elif tag.lower() in {"h1", "h2"} and self._capture == "heading":
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture == "title":
            self.title_text += data
        elif self._capture == "heading":
            self.heading_text += data

    def best_title(self) -> str:
        for value in (self.meta_title, self.title_text, self.heading_text):
            normalized = re.sub(r"\s+", " ", value).strip()
            if normalized:
                return normalized[:200]
        return "未命名参考文章"


def _extract_title(source: str) -> str:
    parser = _PageTitleParser()
    try:
        parser.feed(source)
        parser.close()
        return parser.best_title()
    except Exception:
        matched = _TITLE_RE.search(source)
        if not matched:
            return "未命名参考文章"
        value = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", matched.group(1)))).strip()
        return value[:200] or "未命名参考文章"


def _extract_layout_reference_with_assets(source: str, canonical_url: str, *, truncate: bool = True) -> tuple[str, int, int, list[_AssetSource], str, str | None]:
    for target, label in (("wechat", "公众号正文"), ("article", "article 正文"), ("main", "main 正文"), ("body", "页面正文")):
        parser = _SanitisingCaptureParser(target, preserve_authored=not truncate)
        try:
            parser.feed(source)
            rendered, block_count, image_slots, asset_sources = parser.close_result()
        except LayoutReferenceError:
            raise
        except Exception as exc:
            raise LayoutReferenceError("参考页面 HTML 无法解析") from exc
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(rendered))).strip()
        if parser.found and (plain or image_slots or "<svg" in rendered):
            limited, truncated = _truncate_html(rendered) if truncate else (rendered, False)
            warning = "参考页面较长，已截取主要排版结构" if truncated else None
            return limited, block_count, image_slots, asset_sources, label, warning
    raise LayoutReferenceError("未能从参考页面提取可用正文，请尝试公开文章链接")


def extract_layout_reference(source: str, canonical_url: str) -> tuple[str, int, int, str, str | None]:
    """Compatibility helper used by parser tests and non-fetching callers."""
    rendered, blocks, images, _, label, warning = _extract_layout_reference_with_assets(source, canonical_url)
    return rendered, blocks, images, label, warning


def _truncate_html(source: str) -> tuple[str, bool]:
    if len(source) <= MAX_REFERENCE_HTML_CHARS:
        return source, False
    parser = _HtmlTruncator(MAX_REFERENCE_HTML_CHARS)
    parser.feed(source)
    return parser.result()


def _decode_data_image(source: str) -> tuple[bytes, local_uploads.ImageInfo]:
    matched = _DATA_IMAGE_URL_RE.fullmatch(source.strip())
    if not matched:
        raise LayoutReferenceError("参考图片数据格式不安全或不受支持")
    try:
        data = base64.b64decode(re.sub(r"\s+", "", matched.group(1)), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LayoutReferenceError("参考图片数据无法解码") from exc
    if len(data) > MAX_REFERENCE_IMAGE_BYTES:
        raise LayoutReferenceError("参考图片超过 10MB 限制")
    try:
        return data, local_uploads.inspect_image(data)
    except local_uploads.LocalUploadError as exc:
        raise LayoutReferenceError(str(exc)) from exc


async def _fetch_remote_image(
    client: httpx.AsyncClient, source: str, canonical_url: str
) -> tuple[bytes, local_uploads.ImageInfo]:
    try:
        return await fetch_public_image(client, source, canonical_url)
    except PublicFetchError as exc:
        raise LayoutReferenceError(str(exc)) from exc


async def _fetch_reference_assets(
    asset_sources: list[_AssetSource], canonical_url: str
) -> list[tuple[_AssetSource, bytes, local_uploads.ImageInfo]]:
    if len(asset_sources) > MAX_REFERENCE_IMAGES:
        raise LayoutReferenceError(f"参考页面图片超过 {MAX_REFERENCE_IMAGES} 张，无法完整保留")
    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=FETCH_TIMEOUT_SECONDS)
    semaphore = asyncio.Semaphore(REFERENCE_IMAGE_FETCH_CONCURRENCY)
    total_size = 0
    total_size_lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        async def fetch_one(asset_source: _AssetSource) -> tuple[_AssetSource, bytes, local_uploads.ImageInfo]:
            nonlocal total_size
            async with semaphore:
                if asset_source.source.lower().startswith("data:"):
                    data, image = _decode_data_image(asset_source.source)
                else:
                    data, image = await _fetch_remote_image(client, asset_source.source, canonical_url)
                async with total_size_lock:
                    total_size += len(data)
                    if total_size > MAX_REFERENCE_IMAGE_TOTAL_BYTES:
                        raise LayoutReferenceError("参考图片总大小超过 50MB 限制")
                return asset_source, data, image

        results = await asyncio.gather(*(fetch_one(source) for source in asset_sources))
    return results


def _temporary_asset_key(reference_id: str, asset_id: str, extension: str) -> str:
    return f"local/layout-references/{reference_id}/{asset_id}.{extension}"


_DECORATION_HINT_RE = re.compile(r"(?:tape|sticker|badge|label|icon|logo|deco|ornament|corner|胶带|贴纸|角标|标签|装饰)", re.IGNORECASE)


def _asset_role(source: _AssetSource, image: local_uploads.ImageInfo) -> tuple[str, bool]:
    """Choose conservative defaults; content photos always need an explicit opt-in."""
    if source.background_uses:
        return "背景装饰", True
    if source.positioned_uses:
        return "叠层装饰", True
    if _DECORATION_HINT_RE.search(source.hint_text):
        return "装饰素材", True
    if not source.content_image_uses and image.width and image.height and max(image.width, image.height) <= 360:
        return "装饰素材", True
    return "正文图片", False


def _store_reference_assets(
    reference: LayoutReference, fetched_assets: list[tuple[_AssetSource, bytes, local_uploads.ImageInfo]]
) -> None:
    for source, data, image in fetched_assets:
        role, default_selected = _asset_role(source, image)
        reference.assets.append(
            LayoutReferenceAsset(
                asset_id=source.asset_id,
                object_key="",
                content_type=image.content_type,
                extension=image.extension,
                width=image.width,
                height=image.height,
                usage_count=source.usage_count,
                role=role,
                default_selected=default_selected,
                data=data,
            )
        )


def persist_layout_reference(db: Session, reference: LayoutReference) -> None:
    record = ChatLayoutReference(
        reference_id=reference.reference_id,
        user_id=reference.user_id,
        canonical_url=reference.canonical_url,
        title=reference.title,
        site_name=reference.site_name,
        html_template=reference.html_template,
        block_count=reference.block_count,
        image_slots=reference.image_slots,
        extracted_from=reference.extracted_from,
        warning=reference.warning,
        preview_token_hash=hashlib.sha256(reference.preview_token.encode("utf-8")).hexdigest(),
        preview_token_encrypted=encrypt_secret(reference.preview_token),
        expires_at=_expiry_from_monotonic(reference.expires_at),
    )
    db.add(record)
    for asset in reference.assets:
        if asset.data is None:
            raise LayoutReferenceError("参考图片数据不可用，请重新解析链接")
        db.add(
            ChatLayoutReferenceAsset(
                reference_id=reference.reference_id,
                asset_id=asset.asset_id,
                content_type=asset.content_type,
                extension=asset.extension,
                width=asset.width,
                height=asset.height,
                usage_count=asset.usage_count,
                role=asset.role,
                default_selected=asset.default_selected,
                data=asset.data,
            )
        )
    db.flush()


def materialize_layout_reference(
    reference: LayoutReference,
    db: Session,
    selected_asset_ids: Iterable[str] | None = None,
) -> dict:
    """Copy only the user-approved temporary assets into document image storage."""
    selected = (
        reference.default_selected_asset_ids()
        if selected_asset_ids is None
        else [str(asset_id) for asset_id in selected_asset_ids]
    )
    selected_assets = reference.selected_assets(selected)
    urls: dict[str, str] = {}
    try:
        for asset in selected_assets:
            data = asset.data
            if data is None:
                # Compatibility for an already-created, in-process reference
                # during a rolling upgrade. New references always use DB bytes.
                path = local_uploads.local_path(asset.object_key)
                if not path.is_file():
                    raise LayoutReferenceExpiredError("参考图片已过期或不可用，请重新解析链接")
                data = path.read_bytes()
            urls[asset.asset_id] = store_document_image(db, data, f"layout-reference-{asset.asset_id}")
    except (local_uploads.LocalUploadError, DocumentImageStorageError) as exc:
        raise LayoutReferenceError(f"参考图片保存失败：{exc}") from exc
    return reference.agent_payload(urls, selected)


def replace_session_layout_reference(
    db: Session,
    session_id: int,
    reference: LayoutReference,
    materialized: dict,
    imitation_strength: str = "structure",
) -> ChatSessionLayoutReference:
    """Persist the source-safe template after every approved asset is stable."""
    binding = (
        db.query(ChatSessionLayoutReference)
        .filter(ChatSessionLayoutReference.session_id == session_id)
        .one_or_none()
    )
    if binding is None:
        binding = ChatSessionLayoutReference(session_id=session_id)
        db.add(binding)
    binding.canonical_url = reference.canonical_url
    binding.title = str(materialized.get("title") or reference.title)[:200]
    binding.site_name = str(materialized.get("site_name") or reference.site_name)[:255]
    binding.extracted_from = str(materialized.get("extracted_from") or reference.extracted_from)[:64]
    binding.html_template = str(materialized.get("html") or "")
    binding.block_count = int(materialized.get("block_count") or 0)
    binding.image_slots = int(materialized.get("image_slots") or 0)
    binding.image_assets = int(materialized.get("image_assets") or 0)
    binding.imitation_strength = imitation_strength
    db.flush()
    return binding


def get_session_layout_reference(db: Session, session_id: int) -> ChatSessionLayoutReference | None:
    return (
        db.query(ChatSessionLayoutReference)
        .filter(ChatSessionLayoutReference.session_id == session_id)
        .one_or_none()
    )


def clear_session_layout_reference(db: Session, session_id: int) -> bool:
    return bool(
        db.query(ChatSessionLayoutReference)
        .filter(ChatSessionLayoutReference.session_id == session_id)
        .delete(synchronize_session=False)
    )


def session_layout_reference_agent_payload(binding: ChatSessionLayoutReference | None) -> dict | None:
    if binding is None:
        return None
    return {
        "title": binding.title,
        "site_name": binding.site_name,
        "extracted_from": binding.extracted_from,
        "html": binding.html_template,
        "block_count": binding.block_count,
        "image_slots": binding.image_slots,
        "image_assets": binding.image_assets,
        "imitation_strength": binding.imitation_strength or "structure",
    }


def session_layout_reference_summary(binding: ChatSessionLayoutReference | None) -> dict | None:
    if binding is None:
        return None
    return {
        "title": binding.title,
        "site_name": binding.site_name,
        "extracted_from": binding.extracted_from,
        "block_count": binding.block_count,
        "image_assets": binding.image_assets,
        "imitation_strength": binding.imitation_strength or "structure",
    }


def create_layout_capture_session(raw_url: str, user_id: int, db: Session) -> tuple[LayoutCaptureSession, str]:
    try:
        return create_browser_capture_session(raw_url, user_id, CAPTURE_PURPOSE_LAYOUT_REFERENCE, db)
    except BrowserCaptureError as exc:
        raise LayoutReferenceError(str(exc)) from exc


def _captured_reference_assets(
    asset_sources: list[_AssetSource],
    captured_assets: dict[str, tuple[bytes, local_uploads.ImageInfo]],
) -> list[tuple[_AssetSource, bytes, local_uploads.ImageInfo]]:
    resolved: list[tuple[_AssetSource, bytes, local_uploads.ImageInfo]] = []
    used_ids: set[str] = set()
    for asset_source in asset_sources:
        matched = _CAPTURE_ASSET_URL_RE.fullmatch(asset_source.source)
        if not matched:
            raise LayoutReferenceError("浏览器采集正文包含未授权的外部图片地址")
        captured_id = matched.group(1).lower()
        captured = captured_assets.get(captured_id)
        if captured is None:
            raise LayoutReferenceError("浏览器采集图片清单与正文占位符不一致")
        used_ids.add(captured_id)
        data, image = captured
        resolved.append((asset_source, data, image))
    if used_ids != set(captured_assets):
        raise LayoutReferenceError("浏览器采集图片清单包含正文未引用的素材")
    return resolved


def complete_layout_capture_session(
    db: Session,
    capture_id: str,
    capture_token: str,
    captured_url: str,
    source_html: str,
    title: str,
    captured_assets: dict[str, tuple[bytes, local_uploads.ImageInfo]],
    omitted_asset_count: int = 0,
) -> LayoutReference:
    try:
        capture_session = load_browser_capture_session(
            db,
            capture_id,
            capture_token,
            captured_url,
            CAPTURE_PURPOSE_LAYOUT_REFERENCE,
        )
    except BrowserCaptureExpiredError as exc:
        raise LayoutReferenceExpiredError(str(exc)) from exc
    except BrowserCaptureError as exc:
        raise LayoutReferenceError(str(exc)) from exc
    if len(source_html.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise LayoutReferenceError("浏览器采集正文超过 5MB 限制")
    if len(captured_assets) > MAX_REFERENCE_IMAGES:
        raise LayoutReferenceError(f"浏览器采集图片超过 {MAX_REFERENCE_IMAGES} 张限制")
    if any(len(data) > MAX_REFERENCE_IMAGE_BYTES for data, _ in captured_assets.values()):
        raise LayoutReferenceError("浏览器采集图片超过 10MB 限制")
    if sum(len(data) for data, _ in captured_assets.values()) > MAX_REFERENCE_IMAGE_TOTAL_BYTES:
        raise LayoutReferenceError("浏览器采集图片总大小超过 50MB 限制")

    rendered, block_count, image_slots, asset_sources, _, extraction_warning = (
        _extract_layout_reference_with_assets(source_html, capture_session.canonical_url, truncate=False)
    )
    fetched_assets = _captured_reference_assets(asset_sources, captured_assets)
    warning_parts = [part for part in (extraction_warning,) if part]
    if omitted_asset_count:
        warning_parts.append(f"有 {omitted_asset_count} 个图片素材未能由浏览器采集，已从参考结构中移除")
    normalized_title = re.sub(r"\s+", " ", title).strip()[:200] or "未命名参考文章"
    reference = LayoutReference(
        reference_id=str(uuid4()),
        user_id=capture_session.user_id,
        canonical_url=capture_session.canonical_url,
        title=normalized_title,
        site_name=_WECHAT_HOST,
        html_template=rendered,
        block_count=block_count,
        image_slots=image_slots,
        extracted_from="浏览器采集的公众号正文",
        warning="；".join(warning_parts) or None,
        expires_at=time.monotonic() + REFERENCE_TTL_SECONDS,
        preview_token=token_urlsafe(32),
    )
    _store_reference_assets(reference, fetched_assets)
    complete_browser_capture_session(capture_session)
    persist_layout_reference(db, reference)
    layout_reference_cache.put(reference)
    return reference


async def create_layout_reference(raw_url: str, user_id: int, db: Session) -> LayoutReference:
    canonical_url, source = await _fetch_html(raw_url)
    if _is_wechat_verification_page(source, canonical_url):
        capture_url = _wechat_verification_target_url(canonical_url, raw_url) or canonical_url
        raise WechatVerificationRequiredError(capture_url)
    rendered, block_count, image_slots, asset_sources, extracted_from, warning = _extract_layout_reference_with_assets(source, canonical_url)
    parsed = urlsplit(canonical_url)
    reference = LayoutReference(
        reference_id=str(uuid4()),
        user_id=user_id,
        canonical_url=canonical_url,
        title=_extract_title(source),
        site_name=parsed.hostname or "参考页面",
        html_template=rendered,
        block_count=block_count,
        image_slots=image_slots,
        extracted_from=extracted_from,
        warning=warning,
        expires_at=time.monotonic() + REFERENCE_TTL_SECONDS,
        preview_token=token_urlsafe(32),
    )
    try:
        _store_reference_assets(reference, await _fetch_reference_assets(asset_sources, canonical_url))
    except LayoutReferenceError:
        raise
    except local_uploads.LocalUploadError as exc:
        raise LayoutReferenceError(str(exc)) from exc
    persist_layout_reference(db, reference)
    layout_reference_cache.put(reference)
    return reference
