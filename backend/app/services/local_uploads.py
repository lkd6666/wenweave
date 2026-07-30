"""Private, validated local file storage used only when OSS is unavailable."""
from __future__ import annotations

import os
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Awaitable, Callable
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import DATA_DIR
from app.models.document import DocumentSourceType


LOCAL_KEY_PREFIX = "local/"
LOCAL_UPLOAD_ROOT = DATA_DIR / "uploads"
MANAGED_OBJECT_PREFIX = "local/managed/"
MANAGED_DEFAULT_PREFIX = "yibanpaiban/uploads"
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNCOMPRESSED_SIZE = 150 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 100
MAX_IMAGE_PIXELS = 40_000_000
CHUNK_SIZE = 1024 * 1024


class LocalUploadError(ValueError):
    """An uploaded file does not satisfy the local-storage safety policy."""


@dataclass(frozen=True)
class ImageInfo:
    content_type: str
    extension: str
    width: int = 0
    height: int = 0


def is_local_key(key: str | None) -> bool:
    return bool(key and key.startswith(LOCAL_KEY_PREFIX))


def import_source_key(import_id: str, extension: str) -> str:
    return f"local/direct-imports/{import_id}/source.{extension}"


def import_asset_key(import_id: str, asset_id: str, extension: str) -> str:
    return f"local/direct-imports/{import_id}/assets/{asset_id}.{extension}"


def manual_image_key(extension: str) -> str:
    return f"local/images/{uuid4().hex}.{extension}"


def chat_image_key(attachment_id: str, extension: str) -> str:
    return f"local/chat-images/{attachment_id}.{extension}"


def _managed_relative_key(value: str, *, allow_empty: bool = False) -> str:
    normalized = value.strip().strip("/")
    if not normalized:
        if allow_empty:
            return ""
        raise LocalUploadError("文件路径无效")
    if "\\" in normalized or "\x00" in normalized:
        raise LocalUploadError("文件路径无效")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise LocalUploadError("文件路径无效")
    return "/".join(parts)


def managed_object_path(object_key: str) -> Path:
    """Resolve an administrator-managed local object without exposing app uploads."""
    relative_key = _managed_relative_key(object_key)
    root = local_path(MANAGED_OBJECT_PREFIX.rstrip("/"))
    target = local_path(f"{MANAGED_OBJECT_PREFIX}{relative_key}")
    if root != target and root not in target.parents:
        raise LocalUploadError("文件路径无效")
    return target


def save_managed_object(data: bytes, filename: str, prefix: str = "") -> dict[str, object]:
    """Persist a generic administrator-managed file in the isolated local namespace."""
    safe_name = PurePosixPath(filename.replace("\\", "/")).name.strip() or "file"
    safe_name = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in safe_name)
    folder = _managed_relative_key(prefix, allow_empty=True) or MANAGED_DEFAULT_PREFIX
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    object_key = f"{folder}/{today}/{uuid4().hex}_{safe_name}"
    target = managed_object_path(object_key)
    save_bytes(f"{MANAGED_OBJECT_PREFIX}{object_key}", data, lambda _path: None)
    return {
        "key": object_key,
        "name": safe_name,
        "size": len(data),
        "last_modified": datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc),
        "etag": "",
        "thumbnail_url": None,
    }


def list_managed_objects(prefix: str = "", marker: str = "", limit: int = 100) -> dict[str, object]:
    """List only generic files uploaded through the storage management page."""
    normalized_prefix = _managed_relative_key(prefix, allow_empty=True)
    normalized_marker = _managed_relative_key(marker, allow_empty=True)
    root = local_path(MANAGED_OBJECT_PREFIX.rstrip("/"))
    directory = managed_object_path(normalized_prefix) if normalized_prefix else root
    if not directory.exists():
        return {"objects": [], "prefixes": [], "next_marker": None}
    if not directory.is_dir():
        raise LocalUploadError("目录路径无效")

    entries: list[tuple[str, Path]] = []
    for child in directory.iterdir():
        if child.name.startswith("."):
            continue
        relative_key = child.relative_to(root).as_posix()
        if normalized_marker and relative_key <= normalized_marker:
            continue
        entries.append((relative_key, child))
    entries.sort(key=lambda item: item[0])
    visible = entries[:limit]
    next_marker = visible[-1][0] if len(entries) > limit and visible else None

    objects: list[dict[str, object]] = []
    prefixes: list[dict[str, str]] = []
    for relative_key, child in visible:
        if child.is_dir():
            prefixes.append({"key": relative_key, "name": child.name})
            continue
        if not child.is_file():
            continue
        stat = child.stat()
        objects.append(
            {
                "key": relative_key,
                "name": child.name,
                "size": stat.st_size,
                "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "etag": "",
                "thumbnail_url": None,
            }
        )
    return {"objects": objects, "prefixes": prefixes, "next_marker": next_marker}


def local_path(key: str) -> Path:
    if not is_local_key(key):
        raise LocalUploadError("本地文件路径无效")
    relative = PurePosixPath(key)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise LocalUploadError("本地文件路径无效")
    root = LOCAL_UPLOAD_ROOT.resolve()
    target = (root / Path(*relative.parts)).resolve()
    if root != target and root not in target.parents:
        raise LocalUploadError("本地文件路径无效")
    return target


def delete(key: str) -> None:
    try:
        local_path(key).unlink(missing_ok=True)
    except LocalUploadError:
        return


def _ensure_image_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise LocalUploadError("图片尺寸无效或超过 4000 万像素限制")


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    cursor = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while cursor + 3 < len(data):
        if data[cursor] != 0xFF:
            cursor += 1
            continue
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            break
        marker = data[cursor]
        cursor += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if cursor + 2 > len(data):
            break
        segment_size = struct.unpack(">H", data[cursor : cursor + 2])[0]
        if segment_size < 2 or cursor + segment_size > len(data):
            break
        if marker in sof_markers:
            if segment_size < 8:
                break
            height = struct.unpack(">H", data[cursor + 3 : cursor + 5])[0]
            width = struct.unpack(">H", data[cursor + 5 : cursor + 7])[0]
            return width, height
        cursor += segment_size
    raise LocalUploadError("JPEG 文件缺少有效的尺寸信息")


def _webp_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise LocalUploadError("WebP 文件签名无效")
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    if kind == b"VP8 " and len(data) >= 34 and data[23:26] == b"\x9d\x01\x2a":
        return struct.unpack("<H", data[26:28])[0] & 0x3FFF, struct.unpack("<H", data[28:30])[0] & 0x3FFF
    if kind == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        packed = int.from_bytes(data[21:25], "little")
        return (packed & 0x3FFF) + 1, ((packed >> 14) & 0x3FFF) + 1
    raise LocalUploadError("WebP 文件尺寸信息无效")


def inspect_image(data: bytes) -> ImageInfo:
    """Recognize only browser-safe raster image formats without decoding pixels."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">I", data[16:20])[0], struct.unpack(">I", data[20:24])[0]
        _ensure_image_dimensions(width, height)
        return ImageInfo("image/png", "png", width, height)
    if data.startswith(b"\xff\xd8\xff"):
        width, height = _jpeg_dimensions(data)
        _ensure_image_dimensions(width, height)
        return ImageInfo("image/jpeg", "jpg", width, height)
    if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
        width, height = struct.unpack("<H", data[6:8])[0], struct.unpack("<H", data[8:10])[0]
        _ensure_image_dimensions(width, height)
        return ImageInfo("image/gif", "gif", width, height)
    if data.startswith(b"BM") and len(data) >= 26:
        width = struct.unpack("<i", data[18:22])[0]
        height = abs(struct.unpack("<i", data[22:26])[0])
        _ensure_image_dimensions(width, height)
        return ImageInfo("image/bmp", "bmp", width, height)
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        width, height = _webp_dimensions(data)
        _ensure_image_dimensions(width, height)
        return ImageInfo("image/webp", "webp", width, height)
    # AVIF is an ISO Base Media File. It is not decoded on the server; accept
    # only files explicitly declaring an AVIF compatible brand.
    if len(data) >= 16 and data[4:8] == b"ftyp" and (data[8:12] in {b"avif", b"avis"} or b"avif" in data[16:64]):
        return ImageInfo("image/avif", "avif")
    raise LocalUploadError("文件内容不是受支持的安全图片格式")


def validate_image(path: Path, expected_content_type: str | None = None) -> ImageInfo:
    data = path.read_bytes()
    image = inspect_image(data)
    if expected_content_type and image.content_type != expected_content_type.lower():
        raise LocalUploadError("图片内容与声明的类型不一致")
    return image


def validate_source(path: Path, source_type: DocumentSourceType) -> None:
    if source_type == DocumentSourceType.PDF:
        with path.open("rb") as source:
            header = source.read(1024)
        if b"%PDF-" not in header:
            raise LocalUploadError("文件内容不是有效的 PDF")
        return
    if source_type == DocumentSourceType.MARKDOWN:
        data = path.read_bytes()
        if b"\x00" in data:
            raise LocalUploadError("Markdown 文件不能包含 NUL 字符")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalUploadError("Markdown 文件必须是 UTF-8 编码") from exc
        return
    if source_type != DocumentSourceType.WORD:
        raise LocalUploadError("不支持的源文件类型")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_DOCX_ENTRIES:
                raise LocalUploadError("DOCX 文件条目数量异常")
            names = set()
            uncompressed_size = 0
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                parts = PurePosixPath(name).parts
                if name.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                    raise LocalUploadError("DOCX 文件包含不安全路径")
                if entry.flag_bits & 0x1:
                    raise LocalUploadError("不接受加密的 DOCX 文件")
                if entry.file_size > MAX_DOCX_UNCOMPRESSED_SIZE:
                    raise LocalUploadError("DOCX 文件解压后体积过大")
                if entry.compress_size and entry.file_size > entry.compress_size * MAX_DOCX_COMPRESSION_RATIO:
                    raise LocalUploadError("DOCX 文件压缩比例异常")
                uncompressed_size += entry.file_size
                if uncompressed_size > MAX_DOCX_UNCOMPRESSED_SIZE:
                    raise LocalUploadError("DOCX 文件解压后体积过大")
                names.add(name.lower())
            if "[content_types].xml" not in names or "word/document.xml" not in names:
                raise LocalUploadError("文件不是标准 DOCX 文档")
            if any(name.endswith("vbaproject.bin") for name in names):
                raise LocalUploadError("不接受包含宏的 Word 文件")
    except zipfile.BadZipFile as exc:
        raise LocalUploadError("文件不是有效的 DOCX 压缩包") from exc


Validator = Callable[[Path], None]


async def save_upload(
    upload: UploadFile,
    key: str,
    maximum_size: int,
    expected_size: int,
    validator: Validator,
) -> Path:
    """Write a bounded multipart upload, validate it, then atomically publish it."""
    target = local_path(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.upload")
    size = 0
    try:
        with open(temporary, "xb") as destination:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > maximum_size:
                    raise LocalUploadError("文件超过允许的大小")
                destination.write(chunk)
        if size != expected_size:
            raise LocalUploadError("文件大小与导入任务不一致")
        validator(temporary)
        os.replace(temporary, target)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def save_bytes(key: str, data: bytes, validator: Validator) -> Path:
    target = local_path(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.upload")
    try:
        with open(temporary, "xb") as destination:
            destination.write(data)
        validator(temporary)
        os.replace(temporary, target)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
