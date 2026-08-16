import asyncio
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from app.api.routes import documents, storage
from app.db.base import Base
from app.models.document import Document
from app.models.user import User, UserRole
from app.services import local_uploads
from app.services.gzh_theme_generation import create_reference_asset, read_reference_asset_bytes
from app.services.wechat_official_account import WeChatOfficialAccountClient
from tests.workspace_temp import WorkspaceTempDirectory


PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"


class LocalStorageFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.local_upload_directory = WorkspaceTempDirectory("local-storage")
        self.local_root = patch.object(local_uploads, "LOCAL_UPLOAD_ROOT", Path(self.local_upload_directory.name))
        self.local_root.start()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.admin = User(username="admin", display_name="管理员", password_hash="x", role=UserRole.ADMIN, is_active=True)
        self.user = User(username="writer", display_name="作者", password_hash="x", role=UserRole.USER, is_active=True)
        self.db.add_all([self.admin, self.user])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.local_root.stop()
        self.local_upload_directory.cleanup()

    @staticmethod
    def _upload(data: bytes, filename: str, content_type: str) -> UploadFile:
        return UploadFile(filename=filename, file=BytesIO(data), headers={"content-type": content_type})

    def test_storage_management_uses_isolated_local_namespace_without_oss(self) -> None:
        uploaded = asyncio.run(
            storage.upload_storage_object(
                self._upload(b"local-only", "notes.txt", "text/plain"),
                "reports",
                self.db,
            )
        )
        self.assertTrue(uploaded.key.startswith("reports/"))
        path = local_uploads.managed_object_path(uploaded.key)
        self.assertEqual(path.read_bytes(), b"local-only")

        listing = storage.list_storage_objects("reports", "", 100, self.db)
        self.assertEqual([item.name for item in listing.objects], [])
        day_prefix = listing.prefixes[0].key
        child_listing = storage.list_storage_objects(day_prefix, "", 100, self.db)
        self.assertEqual([item.key for item in child_listing.objects], [uploaded.key])

        preview = storage.preview_storage_object(uploaded.key, self.admin, self.db)
        token = parse_qs(urlparse(preview.url).query)["token"][0]
        response = storage.get_local_storage_object(uploaded.key, token, self.db)
        self.assertEqual(Path(response.path), path)
        self.assertEqual(response.media_type, "text/plain")

        storage.delete_storage_object(uploaded.key, self.db)
        self.assertFalse(path.exists())
        self.assertTrue(storage.test_storage(self.db).success)

    def test_local_cover_and_theme_reference_remain_readable_without_oss(self) -> None:
        document = Document(
            owner_id=self.user.id,
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
            title="本地封面",
            current_html="<p>正文</p>",
        )
        self.db.add(document)
        self.db.commit()

        uploaded = asyncio.run(
            documents.upload_wechat_cover(
                document.id,
                self._upload(PNG, "cover.png", "image/png"),
                self.user,
                self.db,
            )
        )
        self.assertTrue(uploaded.url.startswith("/api/documents/local-images/"))
        payload = documents._local_document_image_payload(self.db, document, uploaded.url)
        self.assertEqual(payload, (PNG, "image/png", uploaded.url.rsplit("/", 1)[-1]))

        reference = create_reference_asset(self.db, uploader_id=self.admin.id, data=PNG, filename="reference.png")
        self.db.commit()
        self.assertEqual(reference.storage_mode, "local")
        self.assertTrue(reference.object_key.startswith("local/theme-references/"))
        self.assertEqual(read_reference_asset_bytes(self.db, reference), PNG)

    def test_wechat_body_sync_can_read_local_image_without_an_http_request(self) -> None:
        client = WeChatOfficialAccountClient()
        client._upload_article_image = AsyncMock(return_value="https://mmbiz.qpic.cn/local.png")  # type: ignore[method-assign]
        source = "/api/documents/local-images/local.png"

        result = asyncio.run(
            client._replace_body_images(
                MagicMock(),
                "token",
                f'<p><img src="{source}" /></p>',
                local_image_loader=lambda value: (PNG, "image/png", "local.png") if value == source else None,
            )
        )

        self.assertIn("https://mmbiz.qpic.cn/local.png", result.html)
        client._upload_article_image.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
