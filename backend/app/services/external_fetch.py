"""Bounded, SSRF-safe fetch helpers for public HTTPS content."""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.services import local_uploads
from app.services.retry_policy import retry_safe_read


FETCH_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_WECHAT_PROXY_HOSTS = {
    "mp.weixin.qq.com",
    "mmbiz.qpic.cn",
    "mmecoa.qpic.cn",
    "res.wx.qq.com",
    "wx.qlogo.cn",
    # Xiumi embeds resolve to the same reserved proxy range in some
    # development/network environments while remaining public asset hosts.
    "img.xiumi.us",
    "statics.xiumi.us",
}
_WECHAT_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_DATA_IMAGE_URL_RE = re.compile(
    r"^data:image/(?:png|jpeg|jpg|gif|webp|avif|bmp);base64,([a-z0-9+/=\s]+)$", re.IGNORECASE
)


class PublicFetchError(ValueError):
    """A requested public resource is unsafe or cannot be retrieved."""

    def __init__(self, message: str, *, response=None):
        super().__init__(message)
        self.status_code = getattr(response, "status_code", None)
        self.headers = getattr(response, "headers", {})


def browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }


def normalize_public_https_url(raw_url: str, *, allow_http: bool = False) -> str:
    """Normalize a public image URL without relaxing the network boundary.

    Page imports remain HTTPS-only.  Article-image localization may opt into
    public HTTP because WeChat itself accepts it, but it still gets the same
    hostname, port and resolved-address checks as HTTPS.
    """
    value = raw_url.strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise PublicFetchError("链接格式无效") from exc
    scheme = parsed.scheme.lower()
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if scheme not in allowed_schemes:
        raise PublicFetchError("仅支持公开 HTTP 或 HTTPS 链接" if allow_http else "仅支持公开 HTTPS 链接")
    if not parsed.hostname or parsed.username or parsed.password:
        raise PublicFetchError("链接必须包含有效域名，且不能包含账号信息")
    try:
        port = parsed.port
    except ValueError as exc:
        raise PublicFetchError("链接端口无效") from exc
    standard_ports = {None, 443, 80} if allow_http else {None, 443}
    if port not in standard_ports:
        raise PublicFetchError("仅支持标准 HTTP 或 HTTPS 端口" if allow_http else "仅支持标准 HTTPS 端口")
    host = parsed.hostname.lower().rstrip(".")
    if not host:
        raise PublicFetchError("链接域名无效")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise PublicFetchError("不允许访问本机或内网地址")
    return urlunsplit((scheme, host, parsed.path or "/", parsed.query, ""))


def _is_allowed_address(host: str, address: str, trusted_proxy_hosts: frozenset[str] = frozenset()) -> bool:
    try:
        parsed_address = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed_address.is_global:
        return True
    hostname = host.lower().rstrip(".")
    return (
        parsed_address.version == 4
        and parsed_address in _WECHAT_PROXY_NETWORK
        and (hostname in _WECHAT_PROXY_HOSTS or hostname in trusted_proxy_hosts)
    )


async def ensure_public_host(url: str, *, trusted_proxy_hosts: frozenset[str] = frozenset()) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise PublicFetchError("链接域名无效")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise PublicFetchError("链接端口无效") from exc
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not literal_ip.is_global:
            raise PublicFetchError("不允许访问本机或内网地址")
        return
    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise PublicFetchError("无法解析链接域名") from exc
    addresses = {record[4][0] for record in records}
    if not addresses or any(not _is_allowed_address(host, address, trusted_proxy_hosts) for address in addresses):
        raise PublicFetchError("链接指向了不允许访问的网络地址")


async def fetch_public_html(raw_url: str) -> tuple[str, str]:
    return await retry_safe_read(lambda: _fetch_public_html_once(raw_url), tool="fetch_article")


async def _fetch_public_html_once(raw_url: str) -> tuple[str, str]:
    current_url = normalize_public_https_url(raw_url)
    headers = {
        **browser_headers(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    }
    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=FETCH_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, headers=headers) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            await ensure_public_host(current_url)
            request_headers = dict(headers)
            host = urlsplit(current_url).hostname or ""
            if host == "mp.weixin.qq.com" or host.endswith(".mp.weixin.qq.com"):
                request_headers["Referer"] = "https://mp.weixin.qq.com/"
            try:
                async with client.stream("GET", current_url, headers=request_headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirect_count >= MAX_REDIRECTS:
                            raise PublicFetchError("链接重定向失败")
                        current_url = normalize_public_https_url(urljoin(current_url, location))
                        continue
                    if response.status_code >= 400:
                        raise PublicFetchError(f"页面无法访问（HTTP {response.status_code}）", response=response)
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                        raise PublicFetchError("链接不是 HTML 页面")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise PublicFetchError("页面过大，无法解析")
                    encoding = response.encoding or "utf-8"
                    try:
                        return current_url, body.decode(encoding, errors="replace")
                    except LookupError:
                        return current_url, body.decode("utf-8", errors="replace")
            except httpx.RequestError as exc:
                raise PublicFetchError(f"获取页面失败：{exc}") from exc
    raise PublicFetchError("链接重定向失败")


def _decode_data_image(source: str) -> tuple[bytes, local_uploads.ImageInfo]:
    matched = _DATA_IMAGE_URL_RE.fullmatch(source.strip())
    if not matched:
        raise PublicFetchError("图片数据格式不安全或不受支持")
    try:
        data = base64.b64decode(re.sub(r"\s+", "", matched.group(1)), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PublicFetchError("图片数据无法解码") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise PublicFetchError("图片超过 10MB 限制")
    try:
        return data, local_uploads.inspect_image(data)
    except local_uploads.LocalUploadError as exc:
        raise PublicFetchError(str(exc)) from exc


async def fetch_public_image(
    client: httpx.AsyncClient,
    source: str,
    canonical_url: str | None = None,
    *,
    trusted_proxy_hosts: set[str] | frozenset[str] | None = None,
    allow_http: bool = False,
) -> tuple[bytes, local_uploads.ImageInfo]:
    return await retry_safe_read(lambda: _fetch_public_image_once(client, source, canonical_url,
        trusted_proxy_hosts=trusted_proxy_hosts, allow_http=allow_http), tool="fetch_image")


async def _fetch_public_image_once(
    client: httpx.AsyncClient,
    source: str,
    canonical_url: str | None = None,
    *,
    trusted_proxy_hosts: set[str] | frozenset[str] | None = None,
    allow_http: bool = False,
) -> tuple[bytes, local_uploads.ImageInfo]:
    if source.lower().startswith("data:"):
        return _decode_data_image(source)
    trusted_hosts = frozenset(
        str(host).lower().rstrip(".") for host in (trusted_proxy_hosts or set()) if str(host).strip()
    )
    current_url = normalize_public_https_url(urljoin(canonical_url or "", source), allow_http=allow_http)
    for redirect_count in range(MAX_REDIRECTS + 1):
        await ensure_public_host(current_url, trusted_proxy_hosts=trusted_hosts)
        headers = {
            **browser_headers(),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if canonical_url:
            headers["Referer"] = canonical_url
        try:
            async with client.stream("GET", current_url, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirect_count >= MAX_REDIRECTS:
                        raise PublicFetchError("图片重定向失败")
                    current_url = normalize_public_https_url(urljoin(current_url, location), allow_http=allow_http)
                    continue
                if response.status_code >= 400:
                    raise PublicFetchError(f"图片无法访问（HTTP {response.status_code}）", response=response)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise PublicFetchError("图片超过 10MB 限制")
                try:
                    return bytes(data), local_uploads.inspect_image(bytes(data))
                except local_uploads.LocalUploadError as exc:
                    raise PublicFetchError(str(exc)) from exc
        except httpx.RequestError as exc:
            raise PublicFetchError(f"获取图片失败：{exc}") from exc
    raise PublicFetchError("图片重定向失败")
