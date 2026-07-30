import asyncio
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.routes import documents
from app.db.base import Base
from app.models.chat_session import ChatSession
from app.models.document import DocumentSourceType
from app.models.document_import import DocumentImport
from app.models.document_visibility import VisibilityMode
from app.models.storage_config import StorageConfig
from app.models.user import User, UserRole
from app.services import local_uploads
from app.schemas.document import (
    DocumentImportAssetCreate,
    DocumentImportAssetsCreate,
    DocumentImportComplete,
    DocumentImportCreate,
    DocumentCreate,
)


class DirectImportRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.local_upload_directory = TemporaryDirectory()
        self.local_root = patch.object(local_uploads, "LOCAL_UPLOAD_ROOT", Path(self.local_upload_directory.name))
        self.local_root.start()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            username="importer",
            display_name="Importer",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add_all(
            [
                self.user,
                StorageConfig(
                    endpoint="oss-cn-test.aliyuncs.com",
                    bucket="test-bucket",
                    access_key_id="test-id",
                    access_key_secret_encrypted="test-secret",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(self.user)

        self.sign_upload = patch(
            "app.api.routes.documents.oss_client.sign_direct_upload",
            side_effect=lambda _config, key, _content_type: f"https://upload.test/{key}",
        )
        self.sign_read = patch(
            "app.api.routes.documents.oss_client.sign_read_url",
            side_effect=lambda _config, key, _expires=0: f"https://read.test/{key}",
        )
        self.inspect = patch(
            "app.api.routes.documents.oss_client.inspect_object",
            side_effect=lambda _config, key: self.uploaded_objects[key],
        )
        self.delete = patch("app.api.routes.documents.oss_client.delete_object")
        self.sign_upload.start()
        self.sign_read.start()
        self.inspect.start()
        self.delete.start()
        self.uploaded_objects: dict[str, dict[str, object]] = {}

    def tearDown(self) -> None:
        self.sign_upload.stop()
        self.sign_read.stop()
        self.inspect.stop()
        self.delete.stop()
        self.db.close()
        self.engine.dispose()
        self.local_root.stop()
        self.local_upload_directory.cleanup()

    @staticmethod
    def _upload(data: bytes, filename: str, content_type: str) -> UploadFile:
        return UploadFile(file=BytesIO(data), filename=filename, headers={"content-type": content_type})

    def test_direct_import_only_signs_fixed_keys_and_completes_once(self) -> None:
        started = documents.create_direct_import(
            DocumentImportCreate(
                filename="campaign.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size=1024,
            ),
            self.user,
            self.db,
        )
        self.assertIn(f"/direct-imports/{started.id}/source.docx", started.source_upload.object_key)
        self.assertNotIn("campaign", started.source_upload.object_key)

        assets = documents.create_direct_import_assets(
            started.id,
            DocumentImportAssetsCreate(
                assets=[
                    DocumentImportAssetCreate(
                        client_id="word-image-1",
                        filename="word-image-1.png",
                        content_type="image/png",
                        size=12,
                    )
                ]
            ),
            self.user,
            self.db,
        )
        self.assertEqual(len(assets.assets), 1)
        asset = assets.assets[0]
        self.assertIn(f"/assets/{asset.asset_id}.png", asset.upload.object_key)

        self.uploaded_objects[started.source_upload.object_key] = {
            "size": 1024,
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        self.uploaded_objects[asset.upload.object_key] = {"size": 12, "content_type": "image/png"}
        result = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html=f'<p><img src="direct-import://asset/{asset.asset_id}" /></p>'),
            self.user,
            self.db,
        )
        self.assertTrue(result.has_source_file)
        self.assertIn("https://read.test/", result.current_html)
        self.assertEqual(result.source_filename, "campaign.docx")
        self.assertEqual(
            self.db.query(ChatSession).filter_by(document_id=result.id, is_archived=False).count(),
            1,
        )

        repeated = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html=f'<p><img src="direct-import://asset/{asset.asset_id}" /></p>'),
            self.user,
            self.db,
        )
        self.assertEqual(repeated.id, result.id)
        self.assertEqual(self.db.query(DocumentImport).filter_by(id=started.id).one().document_id, result.id)

    def test_direct_import_replaces_crop_source_and_display_placeholders(self) -> None:
        started = documents.create_direct_import(
            DocumentImportCreate(
                filename="cropped.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size=1024,
            ),
            self.user,
            self.db,
        )
        assets = documents.create_direct_import_assets(
            started.id,
            DocumentImportAssetsCreate(
                assets=[
                    DocumentImportAssetCreate(
                        client_id="word-source-1",
                        filename="word-source-1.png",
                        content_type="image/png",
                        size=12,
                    ),
                    DocumentImportAssetCreate(
                        client_id="word-crop-1",
                        filename="word-crop-1.png",
                        content_type="image/png",
                        size=16,
                    ),
                ]
            ),
            self.user,
            self.db,
        )
        source_asset, cropped_asset = assets.assets
        self.uploaded_objects[started.source_upload.object_key] = {
            "size": 1024,
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        self.uploaded_objects[source_asset.upload.object_key] = {"size": 12, "content_type": "image/png"}
        self.uploaded_objects[cropped_asset.upload.object_key] = {"size": 16, "content_type": "image/png"}

        result = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(
                html=(
                    f'<p><img src="direct-import://asset/{cropped_asset.asset_id}" '
                    f'data-crop-source="direct-import://asset/{source_asset.asset_id}" '
                    'data-crop-rect="10000,20000,60000,40000" /></p>'
                )
            ),
            self.user,
            self.db,
        )

        self.assertNotIn("direct-import://asset/", result.current_html)
        self.assertIn("data-crop-source=\"https://read.test/", result.current_html)
        self.assertIn("src=\"https://read.test/", result.current_html)

    def test_blank_document_starts_with_an_active_chat_session(self) -> None:
        document = documents.create_document(DocumentCreate(title="空白稿"), self.user, self.db)

        sessions = self.db.query(ChatSession).filter_by(document_id=document.id, is_archived=False).all()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].title, "新对话")

    def test_rejects_missing_or_forged_image_placeholders(self) -> None:
        started = documents.create_direct_import(
            DocumentImportCreate(filename="report.pdf", content_type="application/pdf", size=100),
            self.user,
            self.db,
        )
        self.uploaded_objects[started.source_upload.object_key] = {"size": 100, "content_type": "application/pdf"}
        with self.assertRaises(HTTPException) as context:
            documents.complete_direct_import(
                started.id,
                DocumentImportComplete(html='<p><img src="direct-import://asset/00000000-0000-0000-0000-000000000000" /></p>'),
                self.user,
                self.db,
            )
        self.assertEqual(context.exception.status_code, 400)

    def test_source_access_requires_document_permission(self) -> None:
        started = documents.create_direct_import(
            DocumentImportCreate(filename="report.pdf", content_type="application/pdf", size=100),
            self.user,
            self.db,
        )
        self.uploaded_objects[started.source_upload.object_key] = {"size": 100, "content_type": "application/pdf"}
        document = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html="<p>Report</p>"),
            self.user,
            self.db,
        )
        document.visibility_mode = VisibilityMode.RESTRICTED
        document.allowed_users.append(self.user)
        self.db.commit()
        access = documents.get_document_source_access(document.id, self.user, self.db)
        self.assertEqual(access.filename, "report.pdf")
        self.assertTrue(access.url.startswith("https://read.test/"))

        outsider = User(
            username="outsider",
            display_name="Outsider",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(outsider)
        self.db.commit()
        with self.assertRaises(HTTPException) as context:
            documents.get_document_source_access(document.id, outsider, self.db)
        self.assertEqual(context.exception.status_code, 404)

    def test_server_fallback_imports_only_validated_files_when_oss_is_unconfigured(self) -> None:
        self.db.query(StorageConfig).delete()
        self.db.commit()
        source = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
        started = documents.create_direct_import(
            DocumentImportCreate(filename="report.pdf", content_type="application/pdf", size=len(source)),
            self.user,
            self.db,
        )
        self.assertEqual(started.upload_mode, "server")
        self.assertIsNone(started.source_upload)

        asyncio.run(
            documents.upload_local_import_source(
                started.id,
                self._upload(source, "report.pdf", "application/pdf"),
                self.user,
                self.db,
            )
        )
        assets = documents.create_direct_import_assets(
            started.id,
            DocumentImportAssetsCreate(
                assets=[
                    DocumentImportAssetCreate(
                        client_id="image-1",
                        filename="image-1.png",
                        content_type="image/png",
                        size=24,
                    )
                ]
            ),
            self.user,
            self.db,
        )
        asset = assets.assets[0]
        self.assertIsNone(asset.upload)
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        asyncio.run(
            documents.upload_local_import_asset(
                started.id,
                asset.asset_id,
                self._upload(png, "image-1.png", "image/png"),
                self.user,
                self.db,
            )
        )
        document = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html=f'<img src="direct-import://asset/{asset.asset_id}" />'),
            self.user,
            self.db,
        )
        self.assertTrue(document.source_object_key.startswith("local/"))
        self.assertIn(f"/api/documents/import-assets/{asset.asset_id}", document.current_html)
        self.assertTrue(local_uploads.local_path(document.source_object_key).is_file())
        access = documents.get_document_source_access(document.id, self.user, self.db)
        self.assertIn(f"/api/documents/{document.id}/source-file?token=", access.url)
        token = parse_qs(urlparse(access.url).query)["token"][0]
        source_response = documents.download_local_document_source(document.id, token, self.db)
        self.assertEqual(source_response.media_type, "application/pdf")
        with self.assertRaises(HTTPException) as expired_context:
            documents.download_local_document_source(document.id, "invalid", self.db)
        self.assertEqual(expired_context.exception.status_code, 404)

    def test_server_fallback_rejects_disguised_files_and_unsafe_paths(self) -> None:
        self.db.query(StorageConfig).delete()
        self.db.commit()
        source = b"MZ not a PDF"
        started = documents.create_direct_import(
            DocumentImportCreate(filename="report.pdf", content_type="application/pdf", size=len(source)),
            self.user,
            self.db,
        )
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                documents.upload_local_import_source(
                    started.id,
                    self._upload(source, "report.pdf", "application/pdf"),
                    self.user,
                    self.db,
                )
            )
        self.assertEqual(context.exception.status_code, 400)
        import_session = self.db.get(DocumentImport, started.id)
        self.assertIsNotNone(import_session)
        self.assertFalse(local_uploads.local_path(import_session.source_object_key).exists())
        with self.assertRaises(local_uploads.LocalUploadError):
            local_uploads.local_path("local/../../app.db")
        with self.assertRaises(HTTPException) as svg_context:
            documents.create_direct_import_assets(
                started.id,
                DocumentImportAssetsCreate(
                    assets=[
                        DocumentImportAssetCreate(
                            client_id="dangerous-svg",
                            filename="dangerous.svg",
                            content_type="image/svg+xml",
                            size=32,
                        )
                    ]
                ),
                self.user,
                self.db,
            )
        self.assertEqual(svg_context.exception.status_code, 400)

    def test_markdown_import_accepts_plain_text_and_rejects_invalid_utf8_or_nul(self) -> None:
        self.db.query(StorageConfig).delete()
        self.db.commit()
        source = "# Markdown 标题\n\n正文内容。\n".encode("utf-8")
        started = documents.create_direct_import(
            DocumentImportCreate(filename="article.md", content_type="text/plain", size=len(source)),
            self.user,
            self.db,
        )
        self.assertEqual(started.source_type, DocumentSourceType.MARKDOWN)
        self.assertEqual(started.upload_mode, "server")
        asyncio.run(
            documents.upload_local_import_source(
                started.id,
                self._upload(source, "article.md", "text/markdown"),
                self.user,
                self.db,
            )
        )
        document = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html="<h1>Markdown 标题</h1><p>正文内容。</p>"),
            self.user,
            self.db,
        )
        self.assertEqual(document.source_type, DocumentSourceType.MARKDOWN)
        self.assertEqual(document.source_content_type, "text/markdown")
        access = documents.get_document_source_access(document.id, self.user, self.db)
        self.assertEqual(access.content_type, "text/markdown")

        for filename, invalid_source in (("invalid.md", b"\xff\xfe"), ("nul.md", b"text\x00value")):
            invalid = documents.create_direct_import(
                DocumentImportCreate(filename=filename, content_type="text/markdown", size=len(invalid_source)),
                self.user,
                self.db,
            )
            with self.assertRaises(HTTPException) as context:
                asyncio.run(
                    documents.upload_local_import_source(
                        invalid.id,
                        self._upload(invalid_source, filename, "text/markdown"),
                        self.user,
                        self.db,
                    )
                )
            self.assertEqual(context.exception.status_code, 400)
            session = self.db.get(DocumentImport, invalid.id)
            self.assertIsNotNone(session)
            assert session is not None
            self.assertFalse(local_uploads.local_path(session.source_object_key).exists())

        with self.assertRaises(HTTPException) as content_type_context:
            documents.create_direct_import(
                DocumentImportCreate(filename="article.md", content_type="application/pdf", size=1),
                self.user,
                self.db,
            )
        self.assertEqual(content_type_context.exception.status_code, 400)

    def test_editor_image_uses_validated_local_fallback_when_oss_is_unconfigured(self) -> None:
        self.db.query(StorageConfig).delete()
        self.db.commit()
        document = documents.create_document(DocumentCreate(title="本地图片"), self.user, self.db)
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        uploaded = asyncio.run(
            documents.upload_document_image(
                document.id,
                self._upload(png, "image.png", "image/png"),
                self.user,
                self.db,
            )
        )
        self.assertRegex(uploaded.url, r"^/api/documents/local-images/[0-9a-f]{32}\.png$")
        image_name = uploaded.url.rsplit("/", 1)[-1]
        response = documents.get_local_manual_image(image_name)
        self.assertEqual(response.media_type, "image/png")
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                documents.upload_document_image(
                    document.id,
                    self._upload(b"<svg onload=alert(1) />", "image.png", "image/png"),
                    self.user,
                    self.db,
                )
            )
        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
