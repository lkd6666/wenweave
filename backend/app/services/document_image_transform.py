"""Deterministic raster transforms for document images.

The Agent and the browser image editor deliberately share the same geometry:
rotate first, then crop a rectangle expressed on the rotated image as a
``0..100000`` normalized rectangle.  Keeping this operation server-side makes
the resulting image durable for publishing targets that do not honour CSS
transforms.
"""
from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.services import local_uploads
from app.services.document_images import MAX_DOCUMENT_IMAGE_BYTES


CROP_RECT_SCALE = 100_000
JPEG_QUALITY = 92


class DocumentImageTransformError(ValueError):
    """A requested raster transformation cannot be completed safely."""


@dataclass(frozen=True)
class CropRect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class TransformedDocumentImage:
    data: bytes
    content_type: str
    width: int
    height: int


def _round_pixels(value: float) -> int:
    """Match JavaScript ``Math.round`` for the non-negative crop coordinates."""
    return math.floor(value + 0.5)


def _validate_crop(rect: CropRect | None) -> CropRect | None:
    if rect is None:
        return None
    values = (rect.x, rect.y, rect.width, rect.height)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise DocumentImageTransformError("裁剪范围必须是整数")
    if rect.x < 0 or rect.y < 0 or rect.width <= 0 or rect.height <= 0:
        raise DocumentImageTransformError("裁剪范围无效")
    if rect.x > CROP_RECT_SCALE or rect.y > CROP_RECT_SCALE:
        raise DocumentImageTransformError("裁剪范围超出图片边界")
    if rect.x + rect.width > CROP_RECT_SCALE or rect.y + rect.height > CROP_RECT_SCALE:
        raise DocumentImageTransformError("裁剪范围超出图片边界")
    return rect


def _crop_pixels(rect: CropRect, width: int, height: int) -> tuple[int, int, int, int]:
    # This intentionally mirrors frontend/src/utils/imageCrop.ts. A non-empty
    # normalized rectangle remains at least one source pixel after rounding.
    left = min(max(_round_pixels((rect.x / CROP_RECT_SCALE) * width), 0), width - 1)
    top = min(max(_round_pixels((rect.y / CROP_RECT_SCALE) * height), 0), height - 1)
    right = min(max(_round_pixels(((rect.x + rect.width) / CROP_RECT_SCALE) * width), left + 1), width)
    bottom = min(max(_round_pixels(((rect.y + rect.height) / CROP_RECT_SCALE) * height), top + 1), height)
    return left, top, right, bottom


def _ensure_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > local_uploads.MAX_IMAGE_PIXELS:
        raise DocumentImageTransformError("图片尺寸无效或超过 4000 万像素限制")


def read_document_image_dimensions(data: bytes) -> tuple[str, int, int]:
    """Return safe raster dimensions, decoding AVIF when header parsing cannot.

    ``local_uploads.inspect_image`` intentionally does not parse AVIF box
    metadata and reports zero dimensions for it. Pillow can safely supply the
    dimensions without loading all pixels, after the same pixel ceiling check.
    """
    try:
        info = local_uploads.inspect_image(data)
    except local_uploads.LocalUploadError as exc:
        raise DocumentImageTransformError("图片格式不受支持或尺寸无效") from exc
    if info.width > 0 and info.height > 0:
        return info.content_type, info.width, info.height
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                _ensure_dimensions(image)
                oriented = ImageOps.exif_transpose(image)
                _ensure_dimensions(oriented)
                return info.content_type, oriented.width, oriented.height
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as exc:
        raise DocumentImageTransformError("图片尺寸读取失败") from exc


def _jpeg_image(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def transform_document_image(
    data: bytes,
    *,
    crop: CropRect | None = None,
    rotation_degrees: int = 0,
) -> TransformedDocumentImage:
    """Bake a right-angle rotation and optional post-rotation crop into bytes.

    JPEG and BMP inputs become JPEG; other supported static inputs become PNG,
    matching the browser editor's output policy. GIF is rejected rather than
    silently reducing an animation to one frame.
    """
    if not isinstance(data, bytes) or not data:
        raise DocumentImageTransformError("图片数据无效")
    if len(data) > MAX_DOCUMENT_IMAGE_BYTES:
        raise DocumentImageTransformError("图片不能超过 10MB")
    if isinstance(rotation_degrees, bool) or not isinstance(rotation_degrees, int):
        raise DocumentImageTransformError("旋转角度必须是整数")
    if rotation_degrees not in {0, 90, 180, 270}:
        raise DocumentImageTransformError("仅支持 0、90、180 或 270 度旋转")
    crop = _validate_crop(crop)
    if crop is None and rotation_degrees == 0:
        raise DocumentImageTransformError("请提供裁剪范围或旋转角度")

    try:
        source_info = local_uploads.inspect_image(data)
    except local_uploads.LocalUploadError as exc:
        raise DocumentImageTransformError("图片格式不受支持或尺寸无效") from exc
    if source_info.content_type == "image/gif":
        raise DocumentImageTransformError("暂不支持裁剪或旋转 GIF 动图")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if getattr(source, "is_animated", False):
                    raise DocumentImageTransformError("暂不支持裁剪或旋转 GIF 动图")
                _ensure_dimensions(source)
                image = ImageOps.exif_transpose(source)
                _ensure_dimensions(image)
                image.load()
                if rotation_degrees == 90:
                    image = image.transpose(Image.Transpose.ROTATE_270)
                elif rotation_degrees == 180:
                    image = image.transpose(Image.Transpose.ROTATE_180)
                elif rotation_degrees == 270:
                    image = image.transpose(Image.Transpose.ROTATE_90)
                if crop is not None:
                    image = image.crop(_crop_pixels(crop, *image.size))
                _ensure_dimensions(image)
                content_type = "image/jpeg" if source_info.content_type in {"image/jpeg", "image/bmp"} else "image/png"
                output = io.BytesIO()
                if content_type == "image/jpeg":
                    _jpeg_image(image).save(output, format="JPEG", quality=JPEG_QUALITY)
                else:
                    image.save(output, format="PNG")
    except DocumentImageTransformError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as exc:
        raise DocumentImageTransformError("无法解码或变换图片") from exc

    result = output.getvalue()
    if len(result) > MAX_DOCUMENT_IMAGE_BYTES:
        raise DocumentImageTransformError("变换后的图片超过 10MB 限制")
    try:
        result_info = local_uploads.inspect_image(result)
    except local_uploads.LocalUploadError as exc:
        raise DocumentImageTransformError("变换后的图片校验失败") from exc
    return TransformedDocumentImage(
        data=result,
        content_type=result_info.content_type,
        width=result_info.width,
        height=result_info.height,
    )
