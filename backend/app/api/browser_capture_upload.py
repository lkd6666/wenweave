"""Strict multipart decoding shared by browser capture completion routes."""
from __future__ import annotations

from fastapi import UploadFile
from pydantic import ValidationError

from app.schemas.layout_reference import LayoutCaptureManifest
from app.services import local_uploads
from app.services.browser_capture import MAX_CAPTURE_IMAGE_BYTES, MAX_CAPTURE_IMAGE_TOTAL_BYTES


class BrowserCaptureUploadError(ValueError):
    pass


async def read_browser_capture_upload(
    manifest: str,
    files: list[UploadFile],
) -> tuple[LayoutCaptureManifest, dict[str, tuple[bytes, local_uploads.ImageInfo]]]:
    try:
        capture_manifest = LayoutCaptureManifest.model_validate_json(manifest)
    except ValidationError as exc:
        raise BrowserCaptureUploadError("浏览器采集图片清单格式无效") from exc
    if len(files) != len(capture_manifest.assets):
        raise BrowserCaptureUploadError("浏览器采集图片文件与清单数量不一致")

    captured_assets: dict[str, tuple[bytes, local_uploads.ImageInfo]] = {}
    total_size = 0
    for asset_spec, file in zip(capture_manifest.assets, files, strict=True):
        file_asset_id = (file.filename or "").split(".", 1)[0].lower()
        if file_asset_id != asset_spec.asset_id:
            raise BrowserCaptureUploadError("浏览器采集图片文件与清单顺序不一致")
        data = await file.read(MAX_CAPTURE_IMAGE_BYTES + 1)
        if len(data) > MAX_CAPTURE_IMAGE_BYTES:
            raise BrowserCaptureUploadError("浏览器采集图片超过 10MB 限制")
        if len(data) != asset_spec.size:
            raise BrowserCaptureUploadError("浏览器采集图片大小与清单不一致")
        total_size += len(data)
        if total_size > MAX_CAPTURE_IMAGE_TOTAL_BYTES:
            raise BrowserCaptureUploadError("浏览器采集图片总大小超过 50MB 限制")
        try:
            image = local_uploads.inspect_image(data)
        except local_uploads.LocalUploadError as exc:
            raise BrowserCaptureUploadError(str(exc)) from exc
        declared_type = asset_spec.content_type.lower().replace("image/jpg", "image/jpeg")
        upload_type = (file.content_type or "").lower().replace("image/jpg", "image/jpeg")
        if declared_type != image.content_type or upload_type != image.content_type:
            raise BrowserCaptureUploadError("浏览器采集图片类型与文件内容不一致")
        if asset_spec.asset_id in captured_assets:
            raise BrowserCaptureUploadError("浏览器采集图片清单存在重复素材")
        captured_assets[asset_spec.asset_id] = (data, image)
    return capture_manifest, captured_assets
