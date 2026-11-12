import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes import documents
from app.db.base import Base
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.user import User, UserRole
from app.schemas.document import DocumentHtmlPatch, DocumentUpdate
from app.schemas.wechat import WeChatArticleMetadata
from app.services.document_versions import content_checksum, materialize_document_version
from app.services.html_validation import validate_html_structure
from app.services.image_localization import ImageLocalizationResult
from app.services.wechat_official_account import WeChatApiError, WeChatOfficialAccountClient


class DocumentHtmlValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(username="editor", display_name="Editor", password_hash="unused", role=UserRole.USER, is_active=True)
        self.db.add(self.user)
        self.db.flush()
        self.document = Document(
            owner_id=self.user.id, created_by_id=self.user.id, last_modified_by_id=self.user.id,
            title="结构校验", current_html="<p>正文</p>",
        )
        self.db.add(self.document)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def save_html(self, html: str):
        return documents.patch_document_content(
            self.document.id,
            DocumentHtmlPatch(
                base_checksum=content_checksum(self.document.current_html),
                prefix_length=0, suffix_length=0, replacement=html,
            ),
            self.user, self.db,
        )

    def test_saved_svg_error_matches_sync_diagnostics_and_preserves_the_draft(self) -> None:
        html = '<svg>\n<text x="65" y="34"><br></text>\n</svg>'

        response = self.save_html(html)

        self.assertFalse(response.html_validation.valid)
        self.assertEqual(response.model_dump()["html_validation"], validate_html_structure(html).to_dict())
        self.assertEqual(response.html_validation.issues[0].code, "html5.unexpected-html-element-in-foreign-content")
        with self.assertRaises(WeChatApiError) as raised:
            WeChatOfficialAccountClient.validate_draft_input(
                WeChatArticleMetadata(title="结构校验", cover_url="https://images.example.com/cover.jpg"), html,
            )
        self.assertIn(response.html_validation.errors[0], str(raised.exception))
        self.db.refresh(self.document)
        self.assertEqual(self.document.current_html, html)
        version = self.db.query(DocumentVersion).one()
        self.assertEqual(materialize_document_version(self.db, version), html)

        repaired = self.save_html('<svg>\n<text x="65" y="34">\n</text>\n</svg>')
        self.assertTrue(repaired.html_validation.valid)
        self.assertEqual(repaired.html_validation.errors, [])

    def test_full_content_update_also_returns_structured_diagnostics(self) -> None:
        html = '<svg><text><br></text></svg>'

        response = documents.update_document(
            self.document.id, DocumentUpdate(current_html=html), self.user, self.db,
        )

        self.assertEqual(response.current_html, html)
        self.assertFalse(response.html_validation.valid)
        self.assertEqual(response.model_dump()["html_validation"], validate_html_structure(html).to_dict())

    def test_diagnostics_check_the_actual_saved_html_after_image_processing(self) -> None:
        rewritten = '<svg><text><br></text></svg>'
        with patch(
            "app.api.routes.documents._localize_html_for_document_save",
            return_value=ImageLocalizationResult(html=rewritten, localized_count=0, replacements={}),
        ):
            response = self.save_html('<svg><text>原文</text></svg>')

        self.assertEqual(response.html, rewritten)
        self.assertFalse(response.html_validation.valid)

    def test_valid_svg_html_integration_and_recoverable_warnings_remain_saveable(self) -> None:
        for html in (
            '<svg><text></text><foreignObject><p>第一行<br>第二行</p></foreignObject></svg>',
            '<p><section>正文</section></p>',
        ):
            with self.subTest(html=html):
                response = self.save_html(html)
                self.assertTrue(response.html_validation.valid)
                self.assertEqual(response.html, html)
                self.assertEqual(response.model_dump()["html_validation"], validate_html_structure(html).to_dict())
