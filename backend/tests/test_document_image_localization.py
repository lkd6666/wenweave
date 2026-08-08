import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from app.db.base import Base
from app.models.document import Document
from app.models.template_library import TemplateImageAsset, TemplateLibraryItem, TemplateSourceType
from app.models.user import User, UserRole
from app.services import local_uploads
from app.services.document_image_localization import cleanup_document_localization, localize_document_html
from app.services.local_uploads import ImageInfo


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


class DocumentImageLocalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.local_root = patch.object(local_uploads, "LOCAL_UPLOAD_ROOT", Path(self.directory.name))
        self.local_root.start()
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        user = User(username="writer", display_name="作者", password_hash="x", role=UserRole.USER, is_active=True)
        self.db.add(user)
        self.db.flush()
        self.document = Document(owner_id=user.id, created_by_id=user.id, last_modified_by_id=user.id, title="文章", current_html="<p>正文</p>")
        self.template = TemplateLibraryItem(name="组件", html="<p>组件</p>", source_type=TemplateSourceType.SOURCE)
        self.db.add_all([self.document, self.template])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        self.local_root.stop()
        self.directory.cleanup()

    def test_copies_template_and_external_images_to_local_document_storage_once(self) -> None:
        asset_id = "11111111-1111-1111-1111-111111111111"
        asset_key = f"local/template-library/{asset_id}.png"
        local_uploads.save_bytes(asset_key, PNG, lambda _path: None)
        asset = TemplateImageAsset(
            id=asset_id,
            template_id=self.template.id,
            original_url="https://source.example.test/component.png",
            object_key=asset_key,
            storage_mode="local",
            content_type="image/png",
            size=len(PNG),
        )
        self.db.add(asset)
        self.db.commit()

        fetch = AsyncMock(return_value=(PNG, ImageInfo("image/png", "png")))
        with patch("app.services.document_image_localization.fetch_public_image", new=fetch):
            result = asyncio.run(localize_document_html(
                self.db,
                self.document,
                f'<section style="background:url(https://images.example.test/hero.png)"><img src="https://images.example.test/hero.png" />'
                f'<img src="/api/template-library/assets/{asset_id}" /></section>',
            ))

        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(result.localized_count, 2)
        self.assertNotIn("images.example.test", result.html)
        self.assertNotIn("/api/template-library/assets/", result.html)
        self.assertEqual(result.html.count("/api/documents/local-images/"), 3)
        for stored in result.stored_images:
            self.assertTrue(local_uploads.local_path(stored.handle.object_key).is_file())
        cleanup_document_localization(self.db, result)
        for stored in result.stored_images:
            self.assertFalse(local_uploads.local_path(stored.handle.object_key).exists())
