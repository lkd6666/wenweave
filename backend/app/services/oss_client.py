"""统一对象存储适配层，支持国内主流云厂商的私有 Bucket。"""
from __future__ import annotations

import uuid
from importlib import import_module
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx

from app.core.crypto import decrypt_secret
from app.models.storage_config import StorageConfig


def __getattr__(name: str) -> Any:
    """Keep optional SDK module attributes compatible without eager imports."""
    if name == "qiniu":
        module = import_module("qiniu")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class OSSNotConfiguredError(Exception):
    """Compatibility name retained for existing callers."""


class ObjectStorageError(Exception):
    """A sanitized provider error suitable for an API response."""


ALIYUN_OSS = "aliyun_oss"
TENCENT_COS = "tencent_cos"
HUAWEI_OBS = "huawei_obs"
VOLCENGINE_TOS = "volcengine_tos"
QINIU_KODO = "qiniu_kodo"
SUPPORTED_PROVIDERS = {ALIYUN_OSS, TENCENT_COS, HUAWEI_OBS, VOLCENGINE_TOS, QINIU_KODO}
PROVIDER_LABELS = {
    ALIYUN_OSS: "阿里云 OSS",
    TENCENT_COS: "腾讯云 COS",
    HUAWEI_OBS: "华为云 OBS",
    VOLCENGINE_TOS: "火山引擎 TOS",
    QINIU_KODO: "七牛云 Kodo",
}

# Private objects keep their original access policy. The browser receives a
# time-limited URL only when rendering a document or an image.
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


def _provider(config: StorageConfig) -> str:
    provider = (getattr(config, "provider", "") or ALIYUN_OSS).strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("不支持的对象存储厂商")
    return provider


def provider_label(config: StorageConfig) -> str:
    return PROVIDER_LABELS[_provider(config)]


def _normalize_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        return f"https://{endpoint}"
    return endpoint


def _endpoint_host(endpoint: str) -> str:
    return urlparse(_normalize_endpoint(endpoint)).netloc


def _validate_config(config: StorageConfig, *, require_upload_endpoint: bool = False) -> None:
    provider = _provider(config)
    if not config.access_key_id or not config.access_key_secret_encrypted or not config.bucket:
        raise OSSNotConfiguredError("尚未完成对象存储 AccessKey 和 Bucket 配置")
    if not config.endpoint.strip():
        raise OSSNotConfiguredError("请填写对象存储 Endpoint 或下载域名")
    if provider in {TENCENT_COS, VOLCENGINE_TOS} and not config.region_or_zone.strip():
        raise OSSNotConfiguredError(f"{PROVIDER_LABELS[provider]} 需要填写区域或 Zone")
    if require_upload_endpoint and provider == QINIU_KODO and not config.upload_endpoint.strip():
        raise OSSNotConfiguredError("七牛云 Kodo 需要填写上传 Endpoint")


def _secret(config: StorageConfig) -> str:
    _validate_config(config)
    return decrypt_secret(config.access_key_secret_encrypted)


def _validate_object_key(object_key: str) -> str:
    normalized = object_key.strip().lstrip("/")
    if not normalized or "\x00" in normalized or any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValueError("文件路径无效")
    return normalized


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Qiniu returns putTime in 100ns units.
        timestamp = value / 10_000_000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _value(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _content_type(value: Any) -> str:
    return str(value or "").split(";", 1)[0].lower()


def _provider_error(config: StorageConfig, action: str, exc: Exception) -> ObjectStorageError:
    return ObjectStorageError(f"{provider_label(config)}{action}失败，请检查 Endpoint、区域、Bucket 与访问密钥")


def _build_alibaba_bucket(config: StorageConfig) -> Any:
    import oss2

    return oss2.Bucket(oss2.Auth(config.access_key_id, _secret(config)), _normalize_endpoint(config.endpoint), config.bucket)


def _build_cos_client(config: StorageConfig) -> Any:
    from qcloud_cos import CosConfig, CosS3Client

    return CosS3Client(
        CosConfig(
            Region=config.region_or_zone.strip(),
            SecretId=config.access_key_id,
            SecretKey=_secret(config),
            Scheme=urlparse(_normalize_endpoint(config.endpoint)).scheme,
            Endpoint=_endpoint_host(config.endpoint),
        )
    )


def _build_obs_client(config: StorageConfig) -> Any:
    from obs import ObsClient

    return ObsClient(
        access_key_id=config.access_key_id,
        secret_access_key=_secret(config),
        server=_endpoint_host(config.endpoint),
    )


def _build_tos_client(config: StorageConfig) -> Any:
    import tos

    return tos.TosClientV2(
        ak=config.access_key_id,
        sk=_secret(config),
        endpoint=_normalize_endpoint(config.endpoint),
        region=config.region_or_zone.strip(),
    )


def _build_qiniu_auth(config: StorageConfig) -> Any:
    import qiniu

    return qiniu.Auth(config.access_key_id, _secret(config))


def _qiniu_manager(config: StorageConfig) -> Any:
    import qiniu

    return qiniu.BucketManager(_build_qiniu_auth(config))


def _qiniu_upload_endpoint(config: StorageConfig) -> str:
    _validate_config(config, require_upload_endpoint=True)
    return _normalize_endpoint(config.upload_endpoint)


def build_public_url(config: StorageConfig, object_key: str) -> str:
    key = _validate_object_key(object_key)
    if config.custom_domain:
        return f"{_normalize_endpoint(config.custom_domain)}/{key}"
    endpoint = _normalize_endpoint(config.endpoint)
    if _provider(config) == QINIU_KODO:
        return f"{endpoint}/{key}"
    parsed = urlparse(endpoint)
    return f"{parsed.scheme}://{config.bucket}.{parsed.netloc}/{key}"


def _direct_target(url: str, content_type: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    upload_headers = {key: value for key, value in (headers or {}).items() if key.lower() != "host"}
    if not any(key.lower() == "content-type" for key in upload_headers):
        upload_headers["Content-Type"] = content_type
    return {
        "upload_url": url,
        "upload_method": "PUT",
        "upload_headers": upload_headers,
        "upload_fields": {},
        "file_field_name": "file",
    }


def _qiniu_direct_target(config: StorageConfig, key: str, content_type: str, expires: int) -> dict[str, Any]:
    token = _build_qiniu_auth(config).upload_token(config.bucket, key, expires=expires)
    return {
        "upload_url": _qiniu_upload_endpoint(config),
        "upload_method": "POST",
        "upload_headers": {},
        "upload_fields": {"token": token, "key": key, "mimeType": content_type},
        "file_field_name": "file",
    }


def _put_bytes(config: StorageConfig, key: str, data: bytes, content_type: str | None) -> None:
    provider = _provider(config)
    try:
        if provider == ALIYUN_OSS:
            _build_alibaba_bucket(config).put_object(key, data, headers={"Content-Type": content_type} if content_type else None)
        elif provider == TENCENT_COS:
            kwargs: dict[str, Any] = {"Bucket": config.bucket, "Key": key, "Body": data}
            if content_type:
                kwargs["ContentType"] = content_type
            _build_cos_client(config).put_object(**kwargs)
        elif provider == HUAWEI_OBS:
            response = _build_obs_client(config).putObject(config.bucket, key, data, headers={"Content-Type": content_type} if content_type else None)
            if int(_value(response, "status", default=200)) >= 300:
                raise RuntimeError("OBS returned an unsuccessful status")
        elif provider == VOLCENGINE_TOS:
            _build_tos_client(config).put_object(config.bucket, key, content=data, content_type=content_type)
        else:
            import qiniu

            token = _build_qiniu_auth(config).upload_token(config.bucket, key, expires=DIRECT_UPLOAD_EXPIRE_SECONDS)
            _result, info = qiniu.put_data(token, key, data, mime_type=content_type or "application/octet-stream")
            if not 200 <= int(_value(info, "status_code", "status", default=0)) < 300:
                raise RuntimeError("Kodo returned an unsuccessful status")
    except (OSSNotConfiguredError, ValueError, ObjectStorageError):
        raise
    except Exception as exc:  # SDK exceptions intentionally do not reach API clients verbatim.
        raise _provider_error(config, "上传", exc) from exc


def _read_stream(stream: Any) -> bytes:
    if hasattr(stream, "get_raw_stream"):
        stream = stream.get_raw_stream()
    if hasattr(stream, "read"):
        return stream.read()
    return bytes(stream)


def get_object_bytes(config: StorageConfig, object_key: str) -> bytes:
    key = _validate_object_key(object_key)
    provider = _provider(config)
    try:
        if provider == ALIYUN_OSS:
            return _build_alibaba_bucket(config).get_object(key).read()
        if provider == TENCENT_COS:
            return _read_stream(_build_cos_client(config).get_object(Bucket=config.bucket, Key=key)["Body"])
        if provider == HUAWEI_OBS:
            result = _build_obs_client(config).getObject(config.bucket, key, loadStreamInMemory=True)
            return bytes(result.body.buffer or b"")
        if provider == VOLCENGINE_TOS:
            return _read_stream(_build_tos_client(config).get_object(config.bucket, key))
        response = httpx.get(sign_read_url(config, key), timeout=30.0)
        response.raise_for_status()
        return response.content
    except (OSSNotConfiguredError, ValueError, ObjectStorageError):
        raise
    except Exception as exc:
        raise _provider_error(config, "读取文件", exc) from exc


def put_object_bytes(config: StorageConfig, object_key: str, data: bytes, content_type: Optional[str] = None) -> None:
    _put_bytes(config, _validate_object_key(object_key), data, content_type)


def upload_bytes(config: StorageConfig, data: bytes, filename: str, content_type: Optional[str] = None) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    object_key = f"yibanpaiban/{today}/{uuid.uuid4().hex}.{ext}"
    _put_bytes(config, object_key, data, content_type)
    return sign_read_url(config, object_key, IMAGE_URL_EXPIRE_SECONDS)


def sign_direct_upload(
    config: StorageConfig,
    object_key: str,
    content_type: str,
    expires: int = DIRECT_UPLOAD_EXPIRE_SECONDS,
) -> dict[str, Any]:
    key = _validate_object_key(object_key)
    provider = _provider(config)
    try:
        if provider == ALIYUN_OSS:
            url = _build_alibaba_bucket(config).sign_url("PUT", key, expires, headers={"Content-Type": content_type})
            return _direct_target(url, content_type)
        if provider == TENCENT_COS:
            url = _build_cos_client(config).get_presigned_url(
                Bucket=config.bucket, Key=key, Method="PUT", Expired=expires, Headers={"Content-Type": content_type}
            )
            return _direct_target(url, content_type)
        if provider == HUAWEI_OBS:
            result = _build_obs_client(config).createSignedUrl(
                "PUT", config.bucket, key, expires=expires, headers={"Content-Type": content_type}
            )
            return _direct_target(_value(result, "signedUrl", "signed_url"), content_type, _value(result, "actualSignedRequestHeaders", default={}))
        if provider == VOLCENGINE_TOS:
            from tos.enum import HttpMethodType

            result = _build_tos_client(config).pre_signed_url(
                HttpMethodType.Http_Method_Put, config.bucket, key, expires=expires, header={"Content-Type": content_type}
            )
            return _direct_target(_value(result, "signed_url"), content_type, _value(result, "signed_header", default={}))
        return _qiniu_direct_target(config, key, content_type, expires)
    except (OSSNotConfiguredError, ValueError, ObjectStorageError):
        raise
    except Exception as exc:
        raise _provider_error(config, "生成浏览器直传授权", exc) from exc


def inspect_object(config: StorageConfig, object_key: str) -> dict[str, Any]:
    key = _validate_object_key(object_key)
    provider = _provider(config)
    try:
        if provider == ALIYUN_OSS:
            result = _build_alibaba_bucket(config).head_object(key)
            headers = getattr(result, "headers", {}) or {}
            return {
                "size": int(getattr(result, "content_length", None) or headers.get("Content-Length") or 0),
                "content_type": _content_type(headers.get("Content-Type")),
                "etag": getattr(result, "etag", "") or headers.get("ETag", ""),
            }
        if provider == TENCENT_COS:
            result = _build_cos_client(config).head_object(Bucket=config.bucket, Key=key)
            return {"size": int(result.get("Content-Length", 0)), "content_type": _content_type(result.get("Content-Type")), "etag": result.get("ETag", "")}
        if provider == HUAWEI_OBS:
            result = _build_obs_client(config).getObjectMetadata(config.bucket, key)
            body = _value(result, "body", default=result)
            return {"size": int(_value(body, "contentLength", "content_length", default=0) or 0), "content_type": _content_type(_value(body, "contentType", "content_type")), "etag": str(_value(body, "etag", "eTag", default="") or "")}
        if provider == VOLCENGINE_TOS:
            result = _build_tos_client(config).head_object(config.bucket, key)
            return {"size": int(_value(result, "content_length", default=0) or 0), "content_type": _content_type(_value(result, "content_type")), "etag": str(_value(result, "etag", default="") or "")}
        result, info = _qiniu_manager(config).stat(config.bucket, key)
        if not 200 <= int(_value(info, "status_code", "status", default=0)) < 300:
            raise RuntimeError("Kodo returned an unsuccessful status")
        return {"size": int(_value(result, "fsize", default=0) or 0), "content_type": _content_type(_value(result, "mimeType", "mime_type")), "etag": str(_value(result, "hash", default="") or "")}
    except (OSSNotConfiguredError, ValueError, ObjectStorageError):
        raise
    except Exception as exc:
        raise _provider_error(config, "读取文件元数据", exc) from exc


def _object_entry(key: str, size: Any, last_modified: Any, etag: Any) -> dict[str, Any]:
    return {
        "key": key,
        "name": PurePosixPath(key).name,
        "size": int(size or 0),
        "last_modified": _as_datetime(last_modified),
        "etag": str(etag or ""),
        "thumbnail_url": None,
    }


def _with_thumbnail(config: StorageConfig, entry: dict[str, Any]) -> dict[str, Any]:
    if PurePosixPath(entry["key"]).suffix.lower() in IMAGE_EXTENSIONS:
        entry["thumbnail_url"] = sign_read_url(config, entry["key"], MANAGEMENT_URL_EXPIRE_SECONDS)
    return entry


def list_objects(config: StorageConfig, prefix: str = "", marker: str = "", max_keys: int = 100) -> dict[str, Any]:
    normalized_prefix = prefix.strip().lstrip("/")
    if normalized_prefix and ".." in normalized_prefix.split("/"):
        raise ValueError("目录路径无效")
    if normalized_prefix and not normalized_prefix.endswith("/"):
        normalized_prefix += "/"
    provider = _provider(config)
    try:
        objects: list[dict[str, Any]] = []
        prefixes: list[dict[str, str]] = []
        next_marker: str | None = None
        if provider == ALIYUN_OSS:
            result = _build_alibaba_bucket(config).list_objects(prefix=normalized_prefix, delimiter="/", marker=marker, max_keys=max_keys)
            objects = [_with_thumbnail(config, _object_entry(item.key, item.size, item.last_modified, item.etag)) for item in result.object_list]
            prefixes = [{"key": item.rstrip("/"), "name": PurePosixPath(item.rstrip("/")).name} for item in result.prefix_list]
            next_marker = result.next_marker if result.is_truncated else None
        elif provider == TENCENT_COS:
            result = _build_cos_client(config).list_objects(Bucket=config.bucket, Prefix=normalized_prefix, Delimiter="/", Marker=marker, MaxKeys=max_keys)
            contents = result.get("Contents", [])
            if isinstance(contents, dict):
                contents = [contents]
            objects = [_with_thumbnail(config, _object_entry(item["Key"], item.get("Size"), item.get("LastModified"), item.get("ETag"))) for item in contents]
            common = result.get("CommonPrefixes", [])
            if isinstance(common, dict):
                common = [common]
            prefixes = [{"key": item["Prefix"].rstrip("/"), "name": PurePosixPath(item["Prefix"].rstrip("/")).name} for item in common]
            next_marker = result.get("NextMarker") if str(result.get("IsTruncated", "")).lower() in {"true", "1"} else None
        elif provider == HUAWEI_OBS:
            result = _build_obs_client(config).listObjects(config.bucket, prefix=normalized_prefix, marker=marker or None, max_keys=max_keys, delimiter="/")
            body = _value(result, "body", default=result)
            contents = _value(body, "contents", default=[]) or []
            objects = [_with_thumbnail(config, _object_entry(_value(item, "key"), _value(item, "size"), _value(item, "lastModified", "last_modified"), _value(item, "etag", "eTag"))) for item in contents]
            common = _value(body, "commonPrefixes", "common_prefixes", default=[]) or []
            prefixes = [{"key": str(_value(item, "prefix", default=item)).rstrip("/"), "name": PurePosixPath(str(_value(item, "prefix", default=item)).rstrip("/")).name} for item in common]
            next_marker = str(_value(body, "nextMarker", "next_marker", default="") or "") if bool(_value(body, "isTruncated", "is_truncated", default=False)) else None
        elif provider == VOLCENGINE_TOS:
            result = _build_tos_client(config).list_objects_type2(config.bucket, prefix=normalized_prefix, delimiter="/", continuation_token=marker or None, max_keys=max_keys, list_only_once=True)
            contents = _value(result, "contents", default=[]) or []
            objects = [_with_thumbnail(config, _object_entry(_value(item, "key"), _value(item, "size"), _value(item, "last_modified"), _value(item, "etag"))) for item in contents]
            common = _value(result, "common_prefixes", default=[]) or []
            prefixes = [{"key": str(_value(item, "prefix", default=item)).rstrip("/"), "name": PurePosixPath(str(_value(item, "prefix", default=item)).rstrip("/")).name} for item in common]
            next_marker = str(_value(result, "next_continuation_token", default="") or "") if bool(_value(result, "is_truncated", default=False)) else None
        else:
            result, _eof, info = _qiniu_manager(config).list(config.bucket, prefix=normalized_prefix or None, marker=marker or None, limit=max_keys, delimiter="/")
            if not 200 <= int(_value(info, "status_code", "status", default=0)) < 300:
                raise RuntimeError("Kodo returned an unsuccessful status")
            result = result or {}
            objects = [_with_thumbnail(config, _object_entry(item["key"], item.get("fsize"), item.get("putTime"), item.get("hash"))) for item in result.get("items", [])]
            prefixes = [{"key": str(value).rstrip("/"), "name": PurePosixPath(str(value).rstrip("/")).name} for value in result.get("commonPrefixes", [])]
            next_marker = result.get("marker") or None
        return {"objects": objects, "prefixes": prefixes, "next_marker": next_marker}
    except (OSSNotConfiguredError, ValueError, ObjectStorageError):
        raise
    except Exception as exc:
        raise _provider_error(config, "列举文件", exc) from exc


def sign_read_url(config: StorageConfig, object_key: str, expires: int = MANAGEMENT_URL_EXPIRE_SECONDS) -> str:
    key = _validate_object_key(object_key)
    provider = _provider(config)
    try:
        if provider == ALIYUN_OSS:
            return _build_alibaba_bucket(config).sign_url("GET", key, expires)
        if provider == TENCENT_COS:
            return _build_cos_client(config).get_presigned_url(Bucket=config.bucket, Key=key, Method="GET", Expired=expires)
        if provider == HUAWEI_OBS:
            result = _build_obs_client(config).createSignedUrl("GET", config.bucket, key, expires=expires)
            return str(_value(result, "signedUrl", "signed_url"))
        if provider == VOLCENGINE_TOS:
            from tos.enum import HttpMethodType

            result = _build_tos_client(config).pre_signed_url(HttpMethodType.Http_Method_Get, config.bucket, key, expires=expires)
            return str(_value(result, "signed_url"))
        return _build_qiniu_auth(config).private_download_url(build_public_url(config, key), expires=expires)
    except (OSSNotConfiguredError, ValueError, ObjectStorageError):
        raise
    except Exception as exc:
        raise _provider_error(config, "生成读取授权", exc) from exc


def management_url(config: StorageConfig, object_key: str, expires: int = MANAGEMENT_URL_EXPIRE_SECONDS) -> str:
    return sign_read_url(config, object_key, expires)


def delete_object(config: StorageConfig, object_key: str) -> None:
    key = _validate_object_key(object_key)
    provider = _provider(config)
    try:
        if provider == ALIYUN_OSS:
            _build_alibaba_bucket(config).delete_object(key)
        elif provider == TENCENT_COS:
            _build_cos_client(config).delete_object(Bucket=config.bucket, Key=key)
        elif provider == HUAWEI_OBS:
            result = _build_obs_client(config).deleteObject(config.bucket, key)
            if int(_value(result, "status", default=204)) >= 300:
                raise RuntimeError("OBS returned an unsuccessful status")
        elif provider == VOLCENGINE_TOS:
            _build_tos_client(config).delete_object(config.bucket, key)
        else:
            _result, info = _qiniu_manager(config).delete(config.bucket, key)
            if not 200 <= int(_value(info, "status_code", "status", default=0)) < 300:
                raise RuntimeError("Kodo returned an unsuccessful status")
    except (OSSNotConfiguredError, ValueError, ObjectStorageError):
        raise
    except Exception as exc:
        raise _provider_error(config, "删除文件", exc) from exc


def upload_managed_file(
    config: StorageConfig, data: bytes, filename: str, content_type: Optional[str] = None, prefix: str = ""
) -> dict[str, Any]:
    safe_name = PurePosixPath(filename.replace("\\", "/")).name.strip() or "file"
    safe_name = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in safe_name)
    folder = _validate_object_key(prefix).rstrip("/") if prefix.strip() else "yibanpaiban/uploads"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    object_key = f"{folder}/{today}/{uuid.uuid4().hex}_{safe_name}"
    _put_bytes(config, object_key, data, content_type)
    return {"key": object_key, "name": safe_name, "size": len(data), "last_modified": datetime.now(timezone.utc), "etag": "", "thumbnail_url": None}


def _source_url_key(config: StorageConfig, source: str) -> str | None:
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"}:
        return None
    endpoint_host = _endpoint_host(config.endpoint).lower()
    custom_host = _endpoint_host(config.custom_domain).lower() if config.custom_domain else ""
    allowed_hosts = {endpoint_host, custom_host, f"{config.bucket}.{endpoint_host}"}
    if parsed.netloc.lower() not in allowed_hosts:
        return None
    key = unquote(parsed.path.lstrip("/"))
    return key if key and ".." not in key.split("/") else None


def storage_object_key_for_url(config: StorageConfig, source: str) -> str | None:
    """Return the object key only when a URL belongs to this configured storage."""
    return _source_url_key(config, source)


def refresh_document_image_url(config: StorageConfig, source: str, expires: int = IMAGE_URL_EXPIRE_SECONDS) -> str:
    """Refresh a storage-backed image URL while leaving external images unchanged."""
    object_key = _source_url_key(config, source)
    if not object_key:
        return source
    return sign_read_url(config, object_key, max(1, int(expires)))


def refresh_document_image_urls(
    config: StorageConfig, document_htmls: list[str], expires: int = IMAGE_URL_EXPIRE_SECONDS
) -> tuple[list[str], int]:
    refreshed_htmls: list[str] = []
    object_keys: set[str] = set()
    for html in document_htmls:
        parser = _ImageSourceParser()
        parser.feed(html)
        parser.close()
        refreshed_html = html
        for source in parser.sources:
            object_key = _source_url_key(config, source)
            if not object_key:
                continue
            refreshed_html = refreshed_html.replace(source, refresh_document_image_url(config, source, expires))
            object_keys.add(object_key)
        refreshed_htmls.append(refreshed_html)
    return refreshed_htmls, len(object_keys)


def test_connection(config: StorageConfig) -> Tuple[bool, str]:
    test_payload = b"yibanpaiban connectivity test"
    test_key: str | None = None
    try:
        _validate_config(config)
        test_key = f"yibanpaiban/_connectivity_test/{uuid.uuid4().hex}.txt"
        _put_bytes(config, test_key, test_payload, "text/plain")
        if get_object_bytes(config, test_key) != test_payload:
            raise ObjectStorageError(f"{provider_label(config)}读取测试文件失败")
        delete_object(config, test_key)
        test_key = None
        return True, f"{provider_label(config)}连接成功：读写权限正常"
    except OSSNotConfiguredError as exc:
        return False, str(exc)
    except ObjectStorageError as exc:
        return False, str(exc)
    except Exception:
        return False, f"{provider_label(config)}连接失败，请检查配置与网络"
    finally:
        if test_key:
            try:
                delete_object(config, test_key)
            except Exception:
                pass
