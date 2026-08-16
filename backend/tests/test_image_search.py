from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt

from app.api.routes.image_searches import apply_searched_image
from app.core.security import create_scoped_token
from app.schemas.image_search import ImageSearchApply
from app.services.document_images import StoredDocumentImage
from app.services.html_workspace import HtmlWorkspace
from app.services.image_search import (
    ImageSearchCandidate,
    ImageSearchError,
    ImageSearchTokenError,
    IMAGE_SEARCH_SCOPE,
    _search_cache,
    _search_timeout_seconds,
    decode_candidate_reference,
    decode_candidate_reference_or_token,
    decode_candidate_token,
    issue_candidate_reference,
    issue_candidate_token,
    parse_search_results,
    search_image_page,
    search_images,
    search_images_with_cursor,
)


class _SearchResponse:
    status_code = 200

    def __init__(self, payload: object = None, *, invalid_json: bool = False) -> None:
        self.payload = payload
        self.invalid_json = invalid_json
        self.content = b"{}"

    def json(self) -> object:
        if self.invalid_json:
            raise ValueError("invalid")
        return self.payload


class _SearchClient:
    def __init__(self, response: _SearchResponse | None = None, error: Exception | None = None, **_: object) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    async def __aenter__(self) -> "_SearchClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, *_: object, **__: object) -> _SearchResponse:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


class ImageSearchTests(unittest.TestCase):
    def test_search_timeout_uses_configured_value_without_an_upper_cap(self) -> None:
        with patch(
            "app.services.image_search.get_settings",
            return_value=SimpleNamespace(SEARXNG_TIMEOUT_SECONDS=9.0),
        ):
            self.assertEqual(_search_timeout_seconds(), 9.0)

    def candidate(self) -> ImageSearchCandidate:
        return ImageSearchCandidate(
            id="candidate-1",
            image_url="https://images.example.test/full.jpg",
            preview_url="http://127.0.0.1:8888/image_proxy?url=example",
            source_page_url="https://example.test/article",
            title="茶园",
            engine="bing images",
            width=1600,
            height=900,
            image_format="jpeg",
        )

    def test_parse_results_deduplicates_and_keeps_relative_proxy(self) -> None:
        payload = {
            "results": [
                {
                    "img_src": "https://images.example.test/full.jpg",
                    "thumbnail_src": "/image_proxy?url=first",
                    "url": "https://example.test/article",
                    "title": "茶园",
                    "engine": "bing images",
                    "resolution": "1600x900",
                    "img_format": "jpeg",
                },
                {
                    "img_src": "https://images.example.test/full.jpg",
                    "thumbnail_src": "/image_proxy?url=duplicate",
                    "url": "https://example.test/duplicate",
                },
                {
                    "img_src": "http://insecure.example.test/image.jpg",
                    "thumbnail_src": "https://insecure.example.test/thumb.jpg",
                    "url": "https://insecure.example.test/page",
                },
            ]
        }

        results = parse_search_results(payload, base_url="http://127.0.0.1:8888", orientation="landscape")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].width, 1600)
        self.assertEqual(results[0].height, 900)
        self.assertTrue(results[0].preview_url.startswith("http://127.0.0.1:8888/image_proxy"))

    def test_baidu_http_source_page_is_safely_upgraded(self) -> None:
        payload = {
            "results": [{
                "img_src": "https://gips2.baidu.com/it/u=example.jpg",
                "thumbnail_src": "https://img1.baidu.com/it/u=example.jpg",
                "url": "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=example",
                "engine": "baidu images",
                "title": "城市公园",
            }]
        }

        results = parse_search_results(payload, base_url="http://127.0.0.1:8088")

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].source_page_url,
            "https://mbd.baidu.com/newspage/data/dtlandingsuper?nid=example",
        )

    def test_orientation_keeps_unknown_and_excludes_known_mismatch(self) -> None:
        payload = {
            "results": [
                {"img_src": "https://img.example.test/a.jpg", "thumbnail_src": "https://img.example.test/a-small.jpg", "url": "https://example.test/a", "width": 800, "height": 1200},
                {"img_src": "https://img.example.test/b.jpg", "thumbnail_src": "https://img.example.test/b-small.jpg", "url": "https://example.test/b"},
            ]
        }
        self.assertEqual(len(parse_search_results(payload, base_url="http://127.0.0.1:8888", orientation="portrait")), 2)
        landscape = parse_search_results(payload, base_url="http://127.0.0.1:8888", orientation="landscape")
        self.assertEqual([item.image_url for item in landscape], ["https://img.example.test/b.jpg"])

    def test_parse_results_keeps_more_than_public_page_size(self) -> None:
        payload = {
            "results": [
                {
                    "img_src": f"https://img.example.test/{index}.jpg",
                    "thumbnail_src": f"https://img.example.test/{index}-small.jpg",
                    "url": f"https://example.test/{index}",
                    "engine": "duckduckgo images",
                }
                for index in range(40)
            ]
        }
        results = parse_search_results(payload, base_url="http://127.0.0.1:8088")
        self.assertEqual(len(results), 40)

    def test_candidate_token_is_scoped_to_user_and_document(self) -> None:
        token = issue_candidate_token(self.candidate(), user_id=3, document_id=7)
        visible_claims = jwt.decode(token, options={"verify_signature": False})
        self.assertNotIn("image_url", visible_claims)
        self.assertNotIn(self.candidate().image_url, str(visible_claims))
        decoded = decode_candidate_token(token, user_id=3, document_id=7)
        self.assertEqual(decoded.image_url, self.candidate().image_url)
        with self.assertRaises(ImageSearchTokenError):
            decode_candidate_token(token, user_id=4, document_id=7)
        with self.assertRaises(ImageSearchTokenError):
            decode_candidate_token(token, user_id=3, document_id=8)
        with self.assertRaises(ImageSearchTokenError):
            decode_candidate_token(token + "x", user_id=3, document_id=7)

    def test_compact_candidate_reference_resolves_persisted_search_item(self) -> None:
        token = issue_candidate_token(self.candidate(), user_id=3, document_id=7)
        stored = SimpleNamespace(
            document_id=7,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            content=json.dumps({"items": [{"token": token}]}),
        )
        db = MagicMock()
        db.get.return_value = stored
        db_context = MagicMock()
        db_context.__enter__.return_value = db
        reference = issue_candidate_reference("toolout-candidate-test", 0, user_id=3, document_id=7)

        with patch("app.db.session.SessionLocal", return_value=db_context):
            decoded = decode_candidate_reference(reference, user_id=3, document_id=7)

        self.assertEqual(decoded.id, self.candidate().id)
        with self.assertRaises(ImageSearchTokenError):
            decode_candidate_reference(reference, user_id=4, document_id=7)

    def test_legacy_candidate_token_remains_usable_during_rollout(self) -> None:
        candidate = self.candidate()
        token = create_scoped_token(
            "3",
            IMAGE_SEARCH_SCOPE,
            {
                "document_id": 7,
                "candidate_id": candidate.id,
                "image_url": candidate.image_url,
                "preview_url": "http://127.0.0.1:8888/image_proxy?url=legacy",
                "source_page_url": candidate.source_page_url,
                "title": candidate.title,
                "engine": candidate.engine,
                "width": candidate.width,
                "height": candidate.height,
                "image_format": candidate.image_format,
            },
            expires_in_minutes=120,
        )

        with patch(
            "app.services.image_search._searx_image_proxy_url",
            return_value="http://127.0.0.1:8088/image_proxy?url=resigned",
        ):
            decoded = decode_candidate_token(token, user_id=3, document_id=7)

        self.assertEqual(decoded.image_url, candidate.image_url)
        self.assertTrue(decoded.preview_url.startswith("http://127.0.0.1:8088/image_proxy"))

    def test_full_legacy_token_in_candidate_ref_is_accepted(self) -> None:
        token = issue_candidate_token(self.candidate(), user_id=3, document_id=7)
        decoded = decode_candidate_reference_or_token(token, user_id=3, document_id=7)
        self.assertEqual(decoded.id, self.candidate().id)

    def test_search_results_are_cached_for_page_switching(self) -> None:
        response = _SearchResponse({
            "results": [{
                "img_src": "https://images.example.test/full.jpg",
                "thumbnail_src": "/image_proxy?url=preview",
                "url": "https://example.test/article",
                "title": "茶园",
                "engine": "bing images",
            }]
        })
        client = _SearchClient(response)
        _search_cache.clear()
        try:
            with patch("app.services.image_search.httpx.AsyncClient", return_value=client):
                first = asyncio.run(search_images("缓存测试", page=2))
                second = asyncio.run(search_images("缓存测试", page=2))
        finally:
            _search_cache.clear()

        self.assertEqual(first, second)
        self.assertEqual(client.calls, 1)

    def test_public_page_only_exposes_next_page_when_an_extra_candidate_exists(self) -> None:
        def response_for(count: int) -> _SearchResponse:
            return _SearchResponse({
                "results": [
                    {
                        "img_src": f"https://images.example.test/{index}.jpg",
                        "thumbnail_src": f"https://images.example.test/{index}-small.jpg",
                        "url": f"https://example.test/{index}",
                    }
                    for index in range(count)
                ]
            })

        _search_cache.clear()
        try:
            with patch(
                "app.services.image_search.httpx.AsyncClient",
                return_value=_SearchClient(response_for(12)),
            ):
                items, has_more = asyncio.run(search_image_page("分页测试"))
            self.assertEqual(len(items), 12)
            self.assertFalse(has_more)

            _search_cache.clear()
            with patch(
                "app.services.image_search.httpx.AsyncClient",
                return_value=_SearchClient(response_for(13)),
            ):
                items, has_more = asyncio.run(search_image_page("分页测试"))
            self.assertEqual(len(items), 12)
            self.assertTrue(has_more)
        finally:
            _search_cache.clear()

    def test_agent_cursor_continues_inside_cached_upstream_page(self) -> None:
        response = _SearchResponse({
            "results": [
                {
                    "img_src": f"https://images.example.test/{index}.jpg",
                    "thumbnail_src": f"https://images.example.test/{index}-small.jpg",
                    "url": f"https://example.test/{index}",
                    "title": f"候选 {index}",
                    "engine": "duckduckgo images",
                }
                for index in range(30)
            ]
        })
        client = _SearchClient(response)
        _search_cache.clear()

        async def scenario() -> tuple[list[str], list[str], str | None]:
            first, cursor = await search_images_with_cursor(
                "游标测试",
                purpose="body",
                orientation="landscape",
                cursor="",
                limit=12,
                user_id=3,
                document_id=7,
            )
            assert cursor
            second, next_cursor = await search_images_with_cursor(
                "游标测试",
                purpose="body",
                orientation="landscape",
                cursor=cursor,
                limit=12,
                user_id=3,
                document_id=7,
            )
            return [item.id for item in first], [item.id for item in second], next_cursor

        try:
            with patch("app.services.image_search.httpx.AsyncClient", return_value=client):
                first_ids, second_ids, next_cursor = asyncio.run(scenario())
        finally:
            _search_cache.clear()

        self.assertEqual(len(first_ids), 12)
        self.assertEqual(len(second_ids), 12)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))
        self.assertIsNotNone(next_cursor)
        self.assertEqual(client.calls, 1)

    def test_agent_cursor_rejects_other_user_and_changed_parameters(self) -> None:
        response = _SearchResponse({
            "results": [
                {
                    "img_src": f"https://images.example.test/{index}.jpg",
                    "thumbnail_src": f"https://images.example.test/{index}-small.jpg",
                    "url": f"https://example.test/{index}",
                }
                for index in range(15)
            ]
        })
        client = _SearchClient(response)
        _search_cache.clear()
        try:
            with patch("app.services.image_search.httpx.AsyncClient", return_value=client):
                _, cursor = asyncio.run(search_images_with_cursor(
                    "权限测试", purpose="body", orientation="any", cursor="", limit=12, user_id=3, document_id=7
                ))
                assert cursor
                with self.assertRaises(ImageSearchTokenError):
                    asyncio.run(search_images_with_cursor(
                        "权限测试", purpose="body", orientation="any", cursor=cursor, limit=12, user_id=4, document_id=7
                    ))
                with self.assertRaises(ImageSearchTokenError):
                    asyncio.run(search_images_with_cursor(
                        "不同查询", purpose="body", orientation="any", cursor=cursor, limit=12, user_id=3, document_id=7
                    ))
        finally:
            _search_cache.clear()

    def test_search_service_maps_connection_and_json_failures(self) -> None:
        request = httpx.Request("GET", "http://127.0.0.1:8888/search")
        with patch("app.services.image_search.httpx.AsyncClient", return_value=_SearchClient(error=httpx.ConnectError("down", request=request))):
            with self.assertRaisesRegex(ImageSearchError, "暂时不可用"):
                asyncio.run(search_images("茶园"))
        with patch("app.services.image_search.httpx.AsyncClient", return_value=_SearchClient(_SearchResponse(invalid_json=True))):
            with self.assertRaisesRegex(ImageSearchError, "无效数据"):
                asyncio.run(search_images("茶园"))

    def test_body_application_stores_and_inserts_candidate(self) -> None:
        source_html = "<section><h1>标题</h1><p>正文</p></section>"
        workspace = HtmlWorkspace(source_html)
        heading = next(block for block in workspace.map_payload()["blocks"] if block["tag"] == "h1")
        document = SimpleNamespace(id=7, current_html=source_html)
        payload = ImageSearchApply(
            candidate_token="x" * 20,
            target="body",
            revision=workspace.revision,
            anchor_block_id=heading["block_id"],
            expected_hash=heading["expected_hash"],
            alt="茶园",
        )
        stored = StoredDocumentImage("/api/documents/local-images/search.jpg", "manual/search.jpg", "local")
        db = MagicMock()
        user = SimpleNamespace(id=3)

        with (
            patch("app.api.routes.image_searches._document_or_404", return_value=document),
            patch("app.api.routes.image_searches._require_idle_document"),
            patch("app.api.routes.image_searches.decode_candidate_token", return_value=self.candidate()),
            patch("app.api.routes.image_searches.fetch_candidate_image", new=AsyncMock(return_value=(b"image", SimpleNamespace(content_type="image/jpeg", width=1600, height=900)))),
            patch("app.api.routes.image_searches.store_tracked_document_image", return_value=stored),
            patch("app.api.routes.image_searches.touch_document"),
            patch("app.api.routes.image_searches.create_document_version"),
        ):
            result = asyncio.run(apply_searched_image(7, payload, user, db))

        self.assertEqual(result["target"], "body")
        self.assertIn(stored.url, document.current_html)
        self.assertIn('alt="茶园"', document.current_html)
        db.commit.assert_called_once()

    def test_stale_revision_does_not_store_candidate(self) -> None:
        document = SimpleNamespace(id=7, current_html="<p>当前正文</p>")
        payload = ImageSearchApply(
            candidate_token="x" * 20,
            target="body",
            revision="stale",
            anchor_block_id="block",
            expected_hash="hash",
        )
        db = MagicMock()
        with (
            patch("app.api.routes.image_searches._document_or_404", return_value=document),
            patch("app.api.routes.image_searches._require_idle_document"),
            patch("app.api.routes.image_searches.decode_candidate_token", return_value=self.candidate()),
            patch("app.api.routes.image_searches.fetch_candidate_image", new=AsyncMock(return_value=(b"image", SimpleNamespace(content_type="image/jpeg", width=1600, height=900)))),
            patch("app.api.routes.image_searches.store_tracked_document_image") as store,
        ):
            with self.assertRaises(Exception):
                asyncio.run(apply_searched_image(7, payload, SimpleNamespace(id=3), db))
        store.assert_not_called()

    def test_commit_failure_cleans_up_stored_candidate(self) -> None:
        source_html = "<section><h1>标题</h1><p>正文</p></section>"
        workspace = HtmlWorkspace(source_html)
        heading = next(block for block in workspace.map_payload()["blocks"] if block["tag"] == "h1")
        document = SimpleNamespace(id=7, current_html=source_html)
        payload = ImageSearchApply(
            candidate_token="x" * 20,
            target="body",
            revision=workspace.revision,
            anchor_block_id=heading["block_id"],
            expected_hash=heading["expected_hash"],
        )
        stored = StoredDocumentImage("/api/documents/local-images/search.jpg", "manual/search.jpg", "local")
        db = MagicMock()
        db.commit.side_effect = RuntimeError("database unavailable")

        with (
            patch("app.api.routes.image_searches._document_or_404", return_value=document),
            patch("app.api.routes.image_searches._require_idle_document"),
            patch("app.api.routes.image_searches.decode_candidate_token", return_value=self.candidate()),
            patch("app.api.routes.image_searches.fetch_candidate_image", new=AsyncMock(return_value=(b"image", SimpleNamespace(content_type="image/jpeg", width=1600, height=900)))),
            patch("app.api.routes.image_searches.store_tracked_document_image", return_value=stored),
            patch("app.api.routes.image_searches.delete_tracked_document_image") as cleanup,
            patch("app.api.routes.image_searches.touch_document"),
            patch("app.api.routes.image_searches.create_document_version"),
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                asyncio.run(apply_searched_image(7, payload, SimpleNamespace(id=3), db))

        db.rollback.assert_called_once()
        cleanup.assert_called_once_with(db, stored)


if __name__ == "__main__":
    unittest.main()
