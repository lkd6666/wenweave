import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.document_images import store_document_image
from app.services.layout_reference import LayoutReference, LayoutReferenceAsset, materialize_layout_reference
from app.services.local_uploads import ImageInfo
from tests.workspace_temp import WorkspaceTempDirectory


class DocumentImageStorageTests(unittest.TestCase):
    def test_uses_local_generated_url_when_oss_is_not_configured(self) -> None:
        db = MagicMock()
        image = ImageInfo("image/png", "png")
        with (
            patch("app.services.document_images._storage_if_configured", return_value=None),
            patch("app.services.document_images.local_uploads.inspect_image", return_value=image),
            patch("app.services.document_images.local_uploads.manual_image_key", return_value="local/images/asset.png"),
            patch("app.services.document_images.local_uploads.save_bytes") as save_bytes,
        ):
            url = store_document_image(db, b"png-data", "reference.png")

        self.assertEqual(url, "/api/documents/local-images/asset.png")
        save_bytes.assert_called_once()

    def test_uses_oss_when_storage_is_configured(self) -> None:
        db = MagicMock()
        storage = MagicMock()
        image = ImageInfo("image/webp", "webp")
        with (
            patch("app.services.document_images._storage_if_configured", return_value=storage),
            patch("app.services.document_images.local_uploads.inspect_image", return_value=image),
            patch("app.services.document_images.oss_client.upload_bytes", return_value="https://oss.example/image.webp") as upload_bytes,
        ):
            url = store_document_image(db, b"webp-data", "reference")

        self.assertEqual(url, "https://oss.example/image.webp")
        upload_bytes.assert_called_once_with(storage, b"webp-data", "reference.webp", "image/webp")

    def test_materializing_reference_rewrites_all_asset_markers_to_stable_urls(self) -> None:
        reference = LayoutReference(
            reference_id="reference-id",
            user_id=1,
            canonical_url="https://example.com/article",
            title="参考",
            site_name="example.com",
            html_template=(
                '<section style="background-image:url(&quot;layout-reference://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&quot;)">'
                '<img src="layout-reference://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"></section>'
            ),
            block_count=1,
            image_slots=2,
            extracted_from="article 正文",
            warning=None,
            expires_at=999999999,
            preview_token="preview-token-with-enough-length",
            assets=[
                LayoutReferenceAsset("a" * 32, "local/layout-references/a.png", "image/png", "png"),
                LayoutReferenceAsset("b" * 32, "local/layout-references/b.png", "image/png", "png"),
            ],
        )
        with WorkspaceTempDirectory("document-images") as directory:
            source = Path(directory) / "asset.png"
            source.write_bytes(b"image")
            with (
                patch("app.services.layout_reference.local_uploads.local_path", return_value=source),
                patch(
                    "app.services.layout_reference.store_document_image",
                    side_effect=["/api/documents/local-images/a.png", "/api/documents/local-images/b.png"],
                ),
            ):
                payload = materialize_layout_reference(
                    reference,
                    MagicMock(),
                    selected_asset_ids=["a" * 32, "b" * 32],
                )

        self.assertNotIn("layout-reference://", payload["html"])
        self.assertIn("/api/documents/local-images/a.png", payload["html"])
        self.assertIn("/api/documents/local-images/b.png", payload["html"])
        self.assertEqual(payload["image_assets"], 2)
