"""公开文章排版参考的安全抓取、净化和短期缓存。"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

import httpx

REFERENCE_TTL_SECONDS = 15 * 60
FETCH_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REFERENCE_HTML_CHARS = 48_000
_WECHAT_HOST = "mp.weixin.qq.com"
_WECHAT_COMPAT_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_ALLOWED_TAGS = {
    "article", "section", "div", "p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s",
    "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "br", "hr", "pre", "code",
    "figure", "figcaption", "small", "sup", "sub", "a",
}
_ALLOWED_ATTRIBUTES = {"style", "class", "align", "width", "height", "colspan", "rowspan", "valign"}
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li", "figure", "table", "section"}
_DISCARDED_TAGS = {"script", "style", "iframe", "object", "embed", "template", "noscript", "svg", "canvas", "form", "button", "input"}
_DANGEROUS_STYLE = re.compile(r"(?:url\s*\(|expression\s*\(|@import|behavior\s*:|-moz-binding)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)


class LayoutReferenceError(ValueError):
    pass


class LayoutReferenceExpiredError(LayoutReferenceError):
    pass


@dataclass(frozen=True)
class LayoutReference:
    reference_id: str
    user_id: int
    canonical_url: str
    title: str
    site_name: str
    html: str
    block_count: int
    image_slots: int
    extracted_from: str
    warning: str | None
    expires_at: float

    def preview_payload(self) -> dict:
        return {
            "reference_id": self.reference_id,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "site_name": self.site_name,
            "preview_html": self.html,
            "summary": {
                "block_count": self.block_count,
                "image_slots": self.image_slots,
                "extracted_from": self.extracted_from,
            },
            "warning": self.warning,
        }

    def agent_payload(self) -> dict:
        return {
            "canonical_url": self.canonical_url,
            "title": self.title,
            "site_name": self.site_name,
            "html": self.html,
            "block_count": self.block_count,
            "image_slots": self.image_slots,
            "extracted_from": self.extracted_from,
        }


class _ReferenceCache:
    def __init__(self) -> None:
        self._items: dict[str, LayoutReference] = {}

    def _purge(self) -> None:
        now = time.monotonic()
        for reference_id, item in list(self._items.items()):
            if item.expires_at <= now:
                self._items.pop(reference_id, None)

    def put(self, item: LayoutReference) -> None:
        self._purge()
        self._items[item.reference_id] = item

    def get(self, reference_id: str, user_id: int) -> LayoutReference:
        self._purge()
        item = self._items.get(reference_id)
        if not item or item.user_id != user_id:
            raise LayoutReferenceExpiredError("参考排版已过期或不可用，请重新解析链接")
        return item


layout_reference_cache = _ReferenceCache()


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
    """Allow public addresses and the desktop environment's pinned WeChat proxy range.

    ``198.18.0.0/15`` is normally non-public, so it remains rejected for every
    arbitrary host and for literal IP URLs. The narrow exception only supports
    the official WeChat article host when a local trusted network routes it
    through that address range; HTTPS still validates the WeChat certificate.
    """
    try:
        parsed_address = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed_address.is_global:
        return True
    return host.lower().rstrip(".") == _WECHAT_HOST and parsed_address in _WECHAT_COMPAT_PROXY_NETWORK


async def _fetch_html(raw_url: str) -> tuple[str, str]:
    current_url = _normalise_url(raw_url)
    headers = {
        # 公众号等内容站通常会拦截服务端默认 UA。使用普通浏览器标识，不携带 Cookie，
        # 不绕过登录、付费墙或其他访问控制。
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=FETCH_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, headers=headers) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            await _ensure_public_host(current_url)
            request_headers = dict(headers)
            host = urlsplit(current_url).hostname or ""
            if host == "mp.weixin.qq.com" or host.endswith(".mp.weixin.qq.com"):
                request_headers["Referer"] = "https://mp.weixin.qq.com/"
            try:
                async with client.stream("GET", current_url, headers=request_headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise LayoutReferenceError("参考链接重定向失败")
                        if redirect_count >= MAX_REDIRECTS:
                            raise LayoutReferenceError("参考链接重定向次数过多")
                        current_url = _normalise_url(urljoin(current_url, location))
                        continue
                    if response.status_code >= 400:
                        raise LayoutReferenceError(f"参考页面无法访问（HTTP {response.status_code}）")
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                        raise LayoutReferenceError("参考链接不是 HTML 页面")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise LayoutReferenceError("参考页面过大，无法解析")
                    encoding = response.encoding or "utf-8"
                    try:
                        return current_url, body.decode(encoding, errors="replace")
                    except LookupError:
                        return current_url, body.decode("utf-8", errors="replace")
            except httpx.RequestError as exc:
                raise LayoutReferenceError(f"获取参考页面失败：{exc}") from exc
    raise LayoutReferenceError("参考链接重定向失败")


def _safe_style(value: str) -> str:
    clean = value.strip()
    if not clean or _DANGEROUS_STYLE.search(clean):
        return ""
    declarations: list[str] = []
    for declaration in clean.split(";"):
        property_name, separator, property_value = declaration.partition(":")
        if not separator:
            continue
        normalized_name = property_name.strip().lower()
        normalized_value = property_value.strip().lower().replace("!important", "").strip()
        if normalized_name == "display" and normalized_value == "none":
            continue
        if normalized_name == "visibility" and normalized_value in {"hidden", "collapse"}:
            continue
        if normalized_name == "opacity":
            try:
                if float(normalized_value) <= 0:
                    continue
            except ValueError:
                pass
        if normalized_name == "content-visibility" and normalized_value == "hidden":
            continue
        declarations.append(f"{property_name.strip()}:{property_value.strip()}")
    return ";".join(declarations)[:2000]


def _safe_attributes(attrs: Iterable[tuple[str, str | None]]) -> str:
    values: list[str] = []
    for name, value in attrs:
        normalized = name.lower()
        if normalized not in _ALLOWED_ATTRIBUTES or value is None:
            continue
        if normalized == "style":
            value = _safe_style(value)
            if not value:
                continue
        values.append(f' {normalized}="{html.escape(value[:2000], quote=True)}"')
    return "".join(values)


class _SanitisingCaptureParser(HTMLParser):
    def __init__(self, target: str) -> None:
        super().__init__(convert_charrefs=False)
        self.target = target
        self.capture_depth = 0
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.discard_depth = 0
        self.block_count = 0
        self.image_slots = 0
        self.found = False

    @staticmethod
    def _matches_target(tag: str, attrs: list[tuple[str, str | None]], target: str) -> bool:
        attr_values = {name.lower(): value or "" for name, value in attrs}
        if target == "wechat":
            return attr_values.get("id") == "js_content"
        return tag == target

    def _append_open_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.image_slots += 1
            style = _safe_style(dict((name.lower(), value or "") for name, value in attrs).get("style", ""))
            width = dict((name.lower(), value or "") for name, value in attrs).get("width", "")
            height = dict((name.lower(), value or "") for name, value in attrs).get("height", "")
            image_style = style
            if width and width.isdigit():
                image_style = f"{image_style};width:{width}px" if image_style else f"width:{width}px"
            if height and height.isdigit():
                image_style = f"{image_style};height:{height}px" if image_style else f"height:{height}px"
            style_attr = f' style="{html.escape(image_style, quote=True)}"' if image_style else ""
            self.output.append(f'<span class="layout-reference-image" data-layout-image="true"{style_attr}>图片占位</span>')
            return
        if tag not in _ALLOWED_TAGS:
            return
        if tag in _BLOCK_TAGS:
            self.block_count += 1
        self.output.append(f"<{tag}{_safe_attributes(attrs)}>")
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
            self._append_open_tag(tag.lower(), attrs)

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
                self.output.append(f"</{open_tag}>")
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

    def close_result(self) -> tuple[str, int, int]:
        self.close()
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")
        return "".join(self.output), self.block_count, self.image_slots


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
        value = f"<{tag}{_safe_attributes(attrs)}>"
        if self._append(value) and tag not in _VOID_TAGS:
            self.open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.truncated:
            return
        if tag in self.open_tags:
            while self.open_tags:
                open_tag = self.open_tags.pop()
                self._append(f"</{open_tag}>")
                if open_tag == tag:
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
            self.output.append(f"</{self.open_tags.pop()}>")
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
    except Exception:  # Malformed page title should not prevent body extraction.
        matched = _TITLE_RE.search(source)
        if not matched:
            return "未命名参考文章"
        value = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", matched.group(1)))).strip()
        return value[:200] or "未命名参考文章"


def extract_layout_reference(source: str, canonical_url: str) -> tuple[str, int, int, str, str | None]:
    for target, label in (("wechat", "公众号正文"), ("article", "article 正文"), ("main", "main 正文"), ("body", "页面正文")):
        parser = _SanitisingCaptureParser(target)
        try:
            parser.feed(source)
            rendered, block_count, image_slots = parser.close_result()
        except Exception as exc:  # noqa: BLE001
            raise LayoutReferenceError("参考页面 HTML 无法解析") from exc
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(rendered))).strip()
        if parser.found and plain:
            limited, truncated = _truncate_html(rendered)
            warning = "参考页面较长，已截取主要排版结构" if truncated else None
            return limited, block_count, image_slots, label, warning
    raise LayoutReferenceError("未能从参考页面提取可用正文，请尝试公开文章链接")


def _truncate_html(source: str) -> tuple[str, bool]:
    if len(source) <= MAX_REFERENCE_HTML_CHARS:
        return source, False
    parser = _HtmlTruncator(MAX_REFERENCE_HTML_CHARS)
    parser.feed(source)
    return parser.result()


async def create_layout_reference(raw_url: str, user_id: int) -> LayoutReference:
    canonical_url, source = await _fetch_html(raw_url)
    rendered, block_count, image_slots, extracted_from, warning = extract_layout_reference(source, canonical_url)
    parsed = urlsplit(canonical_url)
    reference = LayoutReference(
        reference_id=str(uuid4()),
        user_id=user_id,
        canonical_url=canonical_url,
        title=_extract_title(source),
        site_name=parsed.hostname or "参考页面",
        html=rendered,
        block_count=block_count,
        image_slots=image_slots,
        extracted_from=extracted_from,
        warning=warning,
        expires_at=time.monotonic() + REFERENCE_TTL_SECONDS,
    )
    layout_reference_cache.put(reference)
    return reference
