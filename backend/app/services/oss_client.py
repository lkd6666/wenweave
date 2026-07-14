"""阿里云 OSS 上传封装：文档导入解析出的图片统一经这里上传并返回外链 URL。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Optional, Tuple
from urllib.parse import unquote, urlparse

import oss2

from app.core.crypto import decrypt_secret
from app.models.storage_config import StorageConfig


class OSSNotConfiguredError(Exception):
    pass


# 私有 Bucket 的图片以长期授权 URL 引用；无需开放 Bucket 或对象 ACL。
IMAGE_URL_EXPIRE_SECONDS = 10 * 365 * 24 * 60 * 60
MANAGEMENT_URL_EXPIRE_SECONDS = 60 * 60
DIRECT_UPLOAD_EXPIRE_SECONDS = 30 * 60
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


class _ImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        for name, value in attrs:
            if name.lower() == "src" and value:
                self.sources.append(value)
                return


def _normalize_endpoint(endpoint: str) -> str:
    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        return f"https://{endpoint}"
    return endpoint


def _build_bucket(config: StorageConfig) -> oss2.Bucket:
    if not config.access_key_id or not config.access_key_secret_encrypted:
        raise OSSNotConfiguredError("尚未配置阿里云 OSS 的 AccessKey")
    secret = decrypt_secret(config.access_key_secret_encrypted)
    auth = oss2.Auth(config.access_key_id, secret)
    return oss2.Bucket(auth, _normalize_endpoint(config.endpoint), config.bucket)


def build_public_url(config: StorageConfig, object_key: str) -> str:
    if config.custom_domain:
        domain = config.custom_domain.rstrip("/")
        return f"{domain}/{object_key}"
    endpoint = config.endpoint
    for prefix in ("https://", "http://"):
        if endpoint.startswith(prefix):
            endpoint = endpoint[len(prefix) :]
            break
    return f"https://{config.bucket}.{endpoint}/{object_key}"


def upload_bytes(config: StorageConfig, data: bytes, filename: str, content_type: Optional[str] = None) -> str:
    bucket = _build_bucket(config)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    object_key = f"yibanpaiban/{today}/{uuid.uuid4().hex}.{ext}"
    headers = {"Content-Type": content_type} if content_type else None
    bucket.put_object(object_key, data, headers=headers)
    return bucket.sign_url("GET", object_key, IMAGE_URL_EXPIRE_SECONDS)


def sign_direct_upload(
    config: StorageConfig,
    object_key: str,
    content_type: str,
    expires: int = DIRECT_UPLOAD_EXPIRE_SECONDS,
) -> str:
    """Issue a PUT URL for one server-generated key without revealing OSS credentials."""
    bucket = _build_bucket(config)
    return bucket.sign_url("PUT", _validate_object_key(object_key), expires, headers={"Content-Type": content_type})


def inspect_object(config: StorageConfig, object_key: str) -> dict[str, Any]:
    """Read only OSS metadata so completion never trusts browser-provided upload state."""
    bucket = _build_bucket(config)
    result = bucket.head_object(_validate_object_key(object_key))
    headers = getattr(result, "headers", {}) or {}
    content_type = headers.get("Content-Type") or headers.get("content-type") or ""
    content_length = getattr(result, "content_length", None)
    if content_length is None:
        content_length = headers.get("Content-Length") or headers.get("content-length") or 0
    return {
        "size": int(content_length),
        "content_type": str(content_type).split(";", 1)[0].lower(),
        "etag": getattr(result, "etag", "") or headers.get("ETag", ""),
    }


def _validate_object_key(object_key: str) -> str:
    normalized = object_key.strip().lstrip("/")
    if not normalized or "\x00" in normalized or any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValueError("文件路径无效")
    return normalized


def list_objects(config: StorageConfig, prefix: str = "", marker: str = "", max_keys: int = 100) -> dict[str, Any]:
    bucket = _build_bucket(config)
    normalized_prefix = prefix.strip().lstrip("/")
    if normalized_prefix and ".." in normalized_prefix.split("/"):
        raise ValueError("目录路径无效")
    if normalized_prefix and not normalized_prefix.endswith("/"):
        normalized_prefix += "/"
    result = bucket.list_objects(
        prefix=normalized_prefix,
        delimiter="/",
        marker=marker,
        max_keys=max_keys,
    )
    objects = []
    for item in result.object_list:
        is_image = PurePosixPath(item.key).suffix.lower() in IMAGE_EXTENSIONS
        objects.append(
            {
                "key": item.key,
                "name": PurePosixPath(item.key).name,
                "size": item.size,
                "last_modified": datetime.fromtimestamp(item.last_modified, tz=timezone.utc)
                if item.last_modified
                else None,
                "etag": item.etag or "",
                # 浏览器只拿到一小时有效的 GET URL；私有 Bucket 也可安全渲染缩略图。
                "thumbnail_url": bucket.sign_url("GET", item.key, MANAGEMENT_URL_EXPIRE_SECONDS) if is_image else None,
            }
        )
    prefixes = [
        {"key": item.rstrip("/"), "name": PurePosixPath(item.rstrip("/")).name}
        for item in result.prefix_list
    ]
    return {
        "objects": objects,
        "prefixes": prefixes,
        "next_marker": result.next_marker if result.is_truncated else None,
    }


def management_url(config: StorageConfig, object_key: str, expires: int = MANAGEMENT_URL_EXPIRE_SECONDS) -> str:
    bucket = _build_bucket(config)
    return bucket.sign_url("GET", _validate_object_key(object_key), expires)


def sign_read_url(config: StorageConfig, object_key: str, expires: int = MANAGEMENT_URL_EXPIRE_SECONDS) -> str:
    bucket = _build_bucket(config)
    return bucket.sign_url("GET", _validate_object_key(object_key), expires)


def delete_object(config: StorageConfig, object_key: str) -> None:
    bucket = _build_bucket(config)
    bucket.delete_object(_validate_object_key(object_key))


def upload_managed_file(
    config: StorageConfig, data: bytes, filename: str, content_type: Optional[str] = None, prefix: str = ""
) -> dict[str, Any]:
    bucket = _build_bucket(config)
    safe_name = PurePosixPath(filename.replace("\\", "/")).name.strip() or "file"
    safe_name = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in safe_name)
    folder = _validate_object_key(prefix).rstrip("/") if prefix.strip() else "yibanpaiban/uploads"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    object_key = f"{folder}/{today}/{uuid.uuid4().hex}_{safe_name}"
    headers = {"Content-Type": content_type} if content_type else None
    bucket.put_object(object_key, data, headers=headers)
    return {
        "key": object_key,
        "name": safe_name,
        "size": len(data),
        "last_modified": datetime.now(timezone.utc),
        "etag": "",
        "thumbnail_url": None,
    }


def _oss_image_sources(config: StorageConfig, html: str) -> dict[str, str]:
    parser = _ImageSourceParser()
    parser.feed(html)
    parser.close()

    endpoint = _normalize_endpoint(config.endpoint)
    endpoint_host = urlparse(endpoint).netloc.lower()
    allowed_hosts = {f"{config.bucket}.{endpoint_host}"}
    if config.custom_domain:
        allowed_hosts.add(urlparse(_normalize_endpoint(config.custom_domain)).netloc.lower())

    sources: dict[str, str] = {}
    for source in parser.sources:
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in allowed_hosts:
            continue
        key = unquote(parsed.path.lstrip("/"))
        if key and ".." not in key.split("/"):
            sources[source] = key
    return sources


def refresh_document_image_urls(config: StorageConfig, document_htmls: list[str]) -> tuple[list[str], int]:
    """将已有推文的 OSS 公网地址改为长期有效的私有对象授权 URL。"""
    bucket = _build_bucket(config)
    refreshed_htmls: list[str] = []
    object_keys: set[str] = set()
    for html in document_htmls:
        refreshed_html = html
        for source, object_key in _oss_image_sources(config, html).items():
            refreshed_html = refreshed_html.replace(
                source,
                bucket.sign_url("GET", object_key, IMAGE_URL_EXPIRE_SECONDS),
            )
            object_keys.add(object_key)
        refreshed_htmls.append(refreshed_html)

    return refreshed_htmls, len(object_keys)


def test_connection(config: StorageConfig) -> Tuple[bool, str]:
    try:
        bucket = _build_bucket(config)
        test_key = f"yibanpaiban/_connectivity_test/{uuid.uuid4().hex}.txt"
        bucket.put_object(test_key, b"yibanpaiban connectivity test")
        bucket.delete_object(test_key)
        return True, "连接成功：读写权限正常"
    except OSSNotConfiguredError as e:
        return False, str(e)
    except oss2.exceptions.OssError as e:
        return False, f"OSS 错误: {e.code} {e.message}"
    except Exception as e:  # noqa: BLE001 兜底捕获网络/证书等未知异常，避免直接 500
        return False, f"连接失败: {e}"
