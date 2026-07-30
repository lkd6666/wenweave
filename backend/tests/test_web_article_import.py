import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.chat_session import ChatSession
from app.models.document import DocumentSourceType
from app.models.user import User, UserRole
from app.models.web_article_import import WebArticleImport, WebArticleImportAsset
from app.services import local_uploads
from app.services.external_fetch import PublicFetchError, fetch_public_html, normalize_public_https_url
from app.services.web_article_import import (
    WebArticleImportError,
    cleanup_expired_web_article_imports,
    complete_web_article_import,
    create_web_article_import,
    get_web_article_import_preview_asset,
    web_article_import_preview_payload,
)


PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"


class WebArticleImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(username="importer", display_name="Importer", password_hash="unused", role=UserRole.USER, is_active=True)
        self.other_user = User(username="other", display_name="Other", password_hash="unused", role=UserRole.USER, is_active=True)
        self.db.add_all([self.user, self.other_user])
        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.other_user)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _create(self, source: str, canonical_url: str = "https://example.com/article"):
        image = local_uploads.inspect_image(PNG)
        with patch(
            "app.services.web_article_import.fetch_public_html",
            new=AsyncMock(return_value=(canonical_url, source)),
        ), patch(
            "app.services.web_article_import.fetch_public_image",
            new=AsyncMock(return_value=(PNG, image)),
        ):
            return asyncio.run(create_web_article_import(canonical_url, self.user.id, self.db))

    def test_wechat_body_is_sanitized_and_materialized_once(self) -> None:
        source = """
        <html><head><title>忽略的标题</title></head><body>
          <h1 id="activity-name">页面标题</h1><div id="js_content">
            <p onclick="alert(1)" style="color: red; background:url(https://bad.example/x)">正文</p>
            <script>alert(1)</script><iframe src="https://bad.example"></iframe>
            <img data-src="/media/a.png" onerror="alert(1)" alt="示例图">
          </div>
        </body></html>
        """
        import_session, preview_token = self._create(source, "https://mp.weixin.qq.com/s/article")

        self.assertEqual(import_session.title, "页面标题")
        self.assertIn("正文", import_session.html_template)
        self.assertIn("web-article-import://asset/", import_session.html_template)
        self.assertNotIn("onclick", import_session.html_template)
        self.assertNotIn("<script", import_session.html_template)
        self.assertNotIn("iframe", import_session.html_template)
        self.assertNotIn("background:url", import_session.html_template)
        self.assertNotIn("https://mp.weixin.qq.com/s/article", import_session.html_template)

        payload = web_article_import_preview_payload(import_session, preview_token)
        self.assertIn(f"/api/documents/link-imports/{import_session.id}/assets/", payload["preview_html"])
        asset = import_session.assets[0]
        self.assertEqual(
            get_web_article_import_preview_asset(self.db, import_session.id, asset.asset_id, preview_token).data,
            PNG,
        )

        with patch("app.services.web_article_import.store_document_image", return_value="/api/documents/local-images/imported.png"):
            document = complete_web_article_import(import_session.id, self.user, self.db)
        self.assertEqual(document.source_type, DocumentSourceType.WEB)
        self.assertFalse(document.has_source_file)
        self.assertEqual(document.wechat_content_source_url, "")
        self.assertIn("/api/documents/local-images/imported.png", document.current_html)
        self.assertEqual(self.db.query(WebArticleImportAsset).filter_by(import_id=import_session.id).count(), 0)
        self.assertEqual(self.db.query(ChatSession).filter_by(document_id=document.id, is_archived=False).count(), 1)

        repeated = complete_web_article_import(import_session.id, self.user, self.db)
        self.assertEqual(repeated.id, document.id)

    def test_failed_https_image_remains_an_external_link_with_a_warning(self) -> None:
        source = "<html><body><article><h1>文章</h1><p>正文</p><img src=\"https://images.example.com/fail.png\"></article></body></html>"
        with patch(
            "app.services.web_article_import.fetch_public_html",
            new=AsyncMock(return_value=("https://example.com/article", source)),
        ), patch(
            "app.services.web_article_import.fetch_public_image",
            new=AsyncMock(side_effect=PublicFetchError("图片无法访问（HTTP 403）")),
        ):
            import_session, _ = asyncio.run(create_web_article_import("https://example.com/article", self.user.id, self.db))

        self.assertEqual(import_session.imported_image_count, 0)
        self.assertEqual(import_session.external_image_count, 1)
        self.assertIn("https://images.example.com/fail.png", import_session.html_template)
        self.assertIn("保留原始外链", import_session.warnings_json)

    def test_generic_page_cover_is_materialized_with_both_default_crops(self) -> None:
        source = """
        <html><head><meta property="og:image" content="/images/cover.png"></head>
        <body><article><h1>通用页面</h1><p>正文</p></article></body></html>
        """
        import_session, preview_token = self._create(source)

        self.assertIsNotNone(import_session.cover_asset_id)
        self.assertTrue(import_session.cover_requires_crops)
        preview = web_article_import_preview_payload(import_session, preview_token)
        self.assertIn(import_session.cover_asset_id or "", preview["cover_preview_url"] or "")

        with patch(
            "app.services.web_article_import.store_document_image",
            side_effect=lambda _db, _data, filename: f"/api/documents/local-images/{filename}",
        ):
            document = complete_web_article_import(import_session.id, self.user, self.db)

        self.assertIn("web-article-", document.wechat_cover_url)
        self.assertEqual(document.wechat_pic_crop_235_1, "0_0.287234_1_0.712766")
        self.assertEqual(document.wechat_pic_crop_1_1, "0_0_1_1")
        self.assertEqual(document.wechat_content_source_url, "")
        self.assertNotIn("https://example.com/article", document.current_html)

    def test_wechat_cover_is_imported_without_default_crops(self) -> None:
        source = """
        <html><head><meta property="og:image" content="https://images.example.com/meta-cover.png"></head>
        <body>
          <div id="js_cover"><img data-src="https://images.example.com/wechat-cover.png"></div>
          <div id="js_content"><p>公众号正文</p></div>
        </body></html>
        """
        requested_sources: list[str] = []
        image = local_uploads.inspect_image(PNG)

        async def fetch_image(_client, source: str, _canonical_url: str):
            requested_sources.append(source)
            return PNG, image

        with patch(
            "app.services.web_article_import.fetch_public_html",
            new=AsyncMock(return_value=("https://mp.weixin.qq.com/s/article", source)),
        ), patch(
            "app.services.web_article_import.fetch_public_image",
            new=fetch_image,
        ):
            import_session, _ = asyncio.run(
                create_web_article_import("https://mp.weixin.qq.com/s/article", self.user.id, self.db)
            )

        self.assertIsNotNone(import_session.cover_asset_id)
        self.assertFalse(import_session.cover_requires_crops)
        self.assertIn("https://images.example.com/wechat-cover.png", requested_sources)
        self.assertNotIn("https://images.example.com/meta-cover.png", requested_sources)
        with patch(
            "app.services.web_article_import.store_document_image",
            return_value="/api/documents/local-images/wechat-cover.png",
        ):
            document = complete_web_article_import(import_session.id, self.user, self.db)

        self.assertEqual(document.wechat_cover_url, "/api/documents/local-images/wechat-cover.png")
        self.assertEqual(document.wechat_pic_crop_235_1, "")
        self.assertEqual(document.wechat_pic_crop_1_1, "")

    def test_cover_fetch_failure_warns_without_blocking_body_import(self) -> None:
        source = """
        <html><head><meta property="og:image" content="https://images.example.com/cover.png"></head>
        <body><article><h1>文章</h1><p>正文</p></article></body></html>
        """
        with patch(
            "app.services.web_article_import.fetch_public_html",
            new=AsyncMock(return_value=("https://example.com/article", source)),
        ), patch(
            "app.services.web_article_import.fetch_public_image",
            new=AsyncMock(side_effect=PublicFetchError("图片无法访问（HTTP 403）")),
        ):
            import_session, _ = asyncio.run(create_web_article_import("https://example.com/article", self.user.id, self.db))

        self.assertIsNone(import_session.cover_asset_id)
        self.assertIn("封面无法保存", import_session.warnings_json)
        document = complete_web_article_import(import_session.id, self.user, self.db)
        self.assertEqual(document.wechat_cover_url, "")

    def test_session_is_user_scoped_and_expired_rows_are_cleaned(self) -> None:
        import_session, _ = self._create("<html><body><article><p>正文</p></article></body></html>")
        import_id = import_session.id
        with self.assertRaises(WebArticleImportError):
            complete_web_article_import(import_id, self.other_user, self.db)

        import_session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.db.commit()
        self.assertEqual(cleanup_expired_web_article_imports(self.db), 1)
        self.assertIsNone(self.db.get(WebArticleImport, import_id))

    def test_external_fetch_only_accepts_public_https_addresses(self) -> None:
        self.assertEqual(normalize_public_https_url("https://Example.com/path#fragment"), "https://example.com/path")
        for value in ("http://example.com", "https://127.0.0.1/a", "https://user:secret@example.com/a"):
            with self.assertRaises(PublicFetchError):
                normalize_public_https_url(value)

    def test_external_fetch_rechecks_redirects_and_requires_html(self) -> None:
        real_client = httpx.AsyncClient

        def redirect_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://127.0.0.1/private"}, request=request)

        with patch(
            "app.services.external_fetch.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(redirect_handler), **kwargs),
        ), patch("app.services.external_fetch.ensure_public_host", new=AsyncMock()):
            with self.assertRaisesRegex(PublicFetchError, "本机或内网"):
                asyncio.run(fetch_public_html("https://example.com/article"))

        def pdf_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-", request=request)

        with patch(
            "app.services.external_fetch.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(pdf_handler), **kwargs),
        ), patch("app.services.external_fetch.ensure_public_host", new=AsyncMock()):
            with self.assertRaisesRegex(PublicFetchError, "不是 HTML"):
                asyncio.run(fetch_public_html("https://example.com/document"))


if __name__ == "__main__":
    unittest.main()
