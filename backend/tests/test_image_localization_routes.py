import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from app.api.routes import documents, template_library
from app.db.base import Base
from app.models.document import Document
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.template_library import TemplateLibraryItem, TemplateSourceType
from app.models.user import User, UserRole
from app.services.image_localization import ImageLocalizationError, ImageLocalizationResult
from app.services.local_uploads import ImageInfo
from app.services.template_library import TemplateImageLocalization, TemplateLibraryError


class ImageLocalizationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(username="writer", display_name="作者", password_hash="x", role=UserRole.USER, is_active=True)
        self.db.add(self.user)
        self.db.flush()
        self.document = Document(
            owner_id=self.user.id,
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
            title="文章",
            current_html='<img src="https://images.example.test/old.png">',
        )
        self.db.add(self.document)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_materialize_returns_copy_without_changing_article(self) -> None:
        template = TemplateLibraryItem(name="组件", html='<img src="/api/template-library/assets/11111111-1111-1111-1111-111111111111">', source_type=TemplateSourceType.SOURCE)
        self.db.add(template)
        self.db.commit()
        result = ImageLocalizationResult(html='<img src="/api/documents/local-images/copied.png">', localized_count=1, replacements={})

        with patch("app.api.routes.documents.localize_document_html", new=AsyncMock(return_value=result)):
            response = asyncio.run(documents.materialize_template_images(self.document.id, template.id, self.user, self.db))

        self.assertEqual(response.html, result.html)
        self.assertEqual(response.localized_count, 1)
        self.db.refresh(self.document)
        self.assertIn("images.example.test", self.document.current_html)

    def test_article_batch_updates_html_and_creates_manual_version(self) -> None:
        result = ImageLocalizationResult(html='<img src="/api/documents/local-images/copied.png">', localized_count=1, replacements={})

        with patch("app.api.routes.documents.localize_document_html", new=AsyncMock(return_value=result)):
            response = asyncio.run(documents.localize_document_images(self.document.id, self.user, self.db))

        self.assertEqual(response.html, result.html)
        self.db.refresh(self.document)
        self.assertEqual(self.document.current_html, result.html)
        version = self.db.query(DocumentVersion).filter(DocumentVersion.document_id == self.document.id).one()
        self.assertEqual(version.source, DocumentVersionSource.MANUAL)
        self.assertEqual(version.label, "转存外链图片")

    def test_article_batch_failure_leaves_html_and_versions_unchanged(self) -> None:
        with patch(
            "app.api.routes.documents.localize_document_html",
            new=AsyncMock(side_effect=ImageLocalizationError("图片无法访问")),
        ):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(documents.localize_document_images(self.document.id, self.user, self.db))

        self.assertEqual(caught.exception.status_code, 422)
        self.db.refresh(self.document)
        self.assertIn("images.example.test", self.document.current_html)
        self.assertEqual(self.db.query(DocumentVersion).count(), 0)

    def test_template_batch_commits_successful_components_and_keeps_failures(self) -> None:
        good = TemplateLibraryItem(name="正常组件", html='<img src="https://images.example.test/good.png">', source_type=TemplateSourceType.SOURCE)
        bad = TemplateLibraryItem(name="失败组件", html='<img src="https://images.example.test/bad.png">', source_type=TemplateSourceType.SOURCE)
        self.db.add_all([good, bad])
        self.db.commit()

        async def localize(_db, template, _html):
            if template.id == bad.id:
                raise TemplateLibraryError("图片无法访问")
            return TemplateImageLocalization(html='<img src="/api/template-library/assets/copied">', localized_count=1, stored_images=())

        with patch("app.api.routes.template_library.localize_template_html", new=localize):
            response = asyncio.run(template_library.localize_template_images(self.user, self.db))

        self.assertEqual(response["updated_count"], 1)
        self.assertEqual(response["failed_count"], 1)
        self.db.refresh(good)
        self.db.refresh(bad)
        self.assertIn("/api/template-library/assets/copied", good.html)
        self.assertIn("images.example.test/bad.png", bad.html)
        states = {item["template_id"]: item["status"] for item in response["items"]}
        self.assertEqual(states[good.id], "updated")
        self.assertEqual(states[bad.id], "failed")

    def test_crop_source_proxy_returns_validated_external_image_bytes(self) -> None:
        with patch(
            "app.api.routes.documents.fetch_public_image",
            new=AsyncMock(return_value=(b"png-data", ImageInfo("image/png", "png"))),
        ):
            response = asyncio.run(
                documents.get_crop_source_image("https://images.example.test/source.png", self.user)
            )

        self.assertEqual(response.body, b"png-data")
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_crop_source_proxy_rejects_unreadable_external_image(self) -> None:
        from app.services.external_fetch import PublicFetchError

        with patch(
            "app.api.routes.documents.fetch_public_image",
            new=AsyncMock(side_effect=PublicFetchError("图片无法访问")),
        ):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(documents.get_crop_source_image("https://images.example.test/source.png", self.user))

        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail, "图片无法访问")
