import asyncio
import base64
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from app.api.routes import documents, template_library
from app.db.base import Base
from app.models.document import Document
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.template_library import TemplateImageAsset, TemplateLibraryItem, TemplateSourceType
from app.models.user import User, UserRole
from app.services import local_uploads
from app.services.image_localization import ImageLocalizationError, ImageLocalizationResult
from app.services.local_uploads import ImageInfo
from app.services.document_versions import content_checksum, materialize_document_version
from app.services.template_library import TemplateImageLocalization, TemplateLibraryError


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
TEST_TMP_PARENT = Path(__file__).resolve().parents[1] / "data" / "test-temp"


class ImageLocalizationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_PARENT.mkdir(parents=True, exist_ok=True)
        self.directory = TEST_TMP_PARENT / f"tmp-{uuid4().hex}"
        self.directory.mkdir(parents=True)
        self.local_root = patch.object(local_uploads, "LOCAL_UPLOAD_ROOT", self.directory)
        self.local_root.start()
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
        self.local_root.stop()
        shutil.rmtree(self.directory, ignore_errors=True)

    def _template_with_asset(self, html: str, asset_id: str = "11111111-1111-1111-1111-111111111111") -> TemplateLibraryItem:
        template = TemplateLibraryItem(name="组件", html=html, source_type=TemplateSourceType.SOURCE)
        self.db.add(template)
        self.db.flush()
        object_key = f"local/template-library/{asset_id}.png"
        local_uploads.save_bytes(object_key, PNG, lambda _path: None)
        self.db.add(TemplateImageAsset(
            id=asset_id,
            template_id=template.id,
            original_url="https://source.example.test/template.png",
            object_key=object_key,
            storage_mode="local",
            content_type="image/png",
            size=len(PNG),
        ))
        self.db.commit()
        return template

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

    def test_materialize_template_asset_src_srcset_and_css_urls_into_article_images(self) -> None:
        template = self._template_with_asset(
            '<section style="background-image:url(\'/api/template-library/assets/11111111-1111-1111-1111-111111111111\');'
            'background:#fff url(/api/template-library/assets/11111111-1111-1111-1111-111111111111) no-repeat">'
            '<img src="/api/template-library/assets/11111111-1111-1111-1111-111111111111" '
            'srcset="/api/template-library/assets/11111111-1111-1111-1111-111111111111 1x, '
            '/api/template-library/assets/11111111-1111-1111-1111-111111111111 2x"></section>'
        )

        response = asyncio.run(documents.materialize_template_images(self.document.id, template.id, self.user, self.db))

        self.assertEqual(response.localized_count, 1)
        self.assertNotIn("/api/template-library/assets/", response.html)
        self.assertEqual(response.html.count("/api/documents/local-images/"), 5)
        self.db.refresh(self.document)
        self.assertNotIn("/api/documents/local-images/", self.document.current_html)

    def test_patch_save_localizes_template_asset_and_persists_saved_html(self) -> None:
        asset_id = "22222222-2222-2222-2222-222222222222"
        self._template_with_asset('<p>unused</p>', asset_id)
        next_html = (
            f'<section style="background-image:url(/api/template-library/assets/{asset_id})">'
            f'<img src="/api/template-library/assets/{asset_id}" srcset="/api/template-library/assets/{asset_id} 1x"></section>'
        )

        response = documents.patch_document_content(
            self.document.id,
            documents.DocumentHtmlPatch(
                base_checksum=content_checksum(self.document.current_html),
                prefix_length=0,
                suffix_length=0,
                replacement=next_html,
            ),
            self.user,
            self.db,
        )

        self.assertEqual(response.localized_count, 1)
        self.assertNotIn("/api/template-library/assets/", response.html)
        self.assertIn("/api/documents/local-images/", response.html)
        self.db.refresh(self.document)
        self.assertEqual(self.document.current_html, response.html)
        version = self.db.query(DocumentVersion).filter(DocumentVersion.document_id == self.document.id).one()
        self.assertEqual(materialize_document_version(self.db, version), response.html)

    def test_patch_save_rejects_blob_file_and_unknown_relative_images(self) -> None:
        self.document.current_html = "<p>正文</p>"
        self.db.commit()
        for source in ["blob:https://app.example/id", "file:///C:/secret.png", "../images/hero.png"]:
            with self.subTest(source=source):
                self.db.refresh(self.document)
                with self.assertRaises(HTTPException) as caught:
                    documents.patch_document_content(
                        self.document.id,
                        documents.DocumentHtmlPatch(
                            base_checksum=content_checksum(self.document.current_html),
                            prefix_length=len(self.document.current_html),
                            suffix_length=0,
                            replacement=f'<img src="{source}">',
                        ),
                        self.user,
                        self.db,
                    )
                self.assertEqual(caught.exception.status_code, 422)
                self.assertIn("正文图片不可发布", str(caught.exception.detail))
                self.db.rollback()

    def test_patch_save_rejects_private_url_without_masking_it_as_public(self) -> None:
        self.document.current_html = "<p>正文</p>"
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            documents.patch_document_content(
                self.document.id,
                documents.DocumentHtmlPatch(
                    base_checksum=content_checksum(self.document.current_html),
                    prefix_length=len(self.document.current_html),
                    suffix_length=0,
                    replacement='<img src="http://127.0.0.1/private.png">',
                ),
                self.user,
                self.db,
            )

        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("内网", str(caught.exception.detail))
        self.db.refresh(self.document)
        self.assertNotIn("127.0.0.1", self.document.current_html)

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

    def test_localization_does_not_overwrite_edits_made_during_download(self) -> None:
        result = ImageLocalizationResult(html='<img src="/copied.png">', localized_count=1, replacements={})
        document_id = self.document.id

        async def download(*_args):
            with Session(self.engine) as other:
                other.get(Document, document_id).current_html = '<p>newer external edit</p>'
                other.commit()
            return result

        with (patch.object(documents, 'localize_document_html', side_effect=download),
              patch.object(documents, 'cleanup_document_localization') as cleanup):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(documents.localize_document_images(document_id, self.user, self.db))
        self.assertEqual(caught.exception.status_code, 409)
        cleanup.assert_called_once_with(self.db, result)
        self.db.refresh(self.document)
        self.assertEqual(self.document.current_html, '<p>newer external edit</p>')
        self.assertEqual(self.db.query(DocumentVersion).count(), 0)

    def test_localization_rejects_run_started_during_download(self) -> None:
        original = self.document.current_html
        result = ImageLocalizationResult(html='<img src="/copied.png">', localized_count=1, replacements={})
        document_id, user_id = self.document.id, self.user.id

        async def download(*_args):
            with Session(self.engine) as other:
                session = ChatSession(document_id=document_id, title='test')
                other.add(session)
                other.flush()
                message = ChatMessage(document_id=document_id, session_id=session.id,
                                      role=MessageRole.USER, content='test')
                other.add(message)
                other.flush()
                other.add(AgentRun(id='new-run', document_id=document_id, user_id=user_id,
                                   session_id=session.id, user_message_id=message.id,
                                   client_request_id='new-run', status=AgentRunStatus.RUNNING))
                other.commit()
            return result

        with (patch.object(documents, 'localize_document_html', side_effect=download),
              patch.object(documents, 'cleanup_document_localization') as cleanup):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(documents.localize_document_images(document_id, self.user, self.db))
        self.assertEqual(caught.exception.status_code, 409)
        cleanup.assert_called_once()
        self.db.refresh(self.document)
        self.assertEqual(self.document.current_html, original)

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
