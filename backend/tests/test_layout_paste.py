import asyncio
import base64
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import httpx
import app.models
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.base import Base
from app.api.routes.layout_references import paste_layout_reference
from app.schemas.layout_reference import LayoutReferencePasteRequest
from app.services.layout_reference import create_pasted_layout_reference, get_layout_reference, LayoutReferenceError
from tests.test_layout_reference import PNG


class LayoutPasteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_plain_text_escapes_markup_and_preserves_paragraphs(self):
        ref = await create_pasted_layout_reference('标题\n正文 <script>文本</script> & 原文', 'text', '', 1, self.db)
        self.assertIn('&lt;script&gt;', ref.html_template)
        self.assertIn('<p>标题</p>', ref.html_template)
        self.assertEqual(get_layout_reference(self.db, ref.reference_id, 1).reference_id, ref.reference_id)

    async def test_html_fragment_and_document_are_sanitized_without_network(self):
        for prefix, suffix in [('', ''), ('<html><head><title>参考</title><style>.x{color:red}</style></head><body>', '</body></html>')]:
            source = prefix + '<section style="color:#123456"><p onclick="evil()">参考文字</p><script>evil()</script><iframe src="http://127.0.0.1"></iframe><img src="http://127.0.0.1/secret"><div style="background:url(file:///secret)">块</div></section>' + suffix
            with patch('app.services.layout_reference.fetch_public_image', new_callable=AsyncMock) as fetch:
                ref = await create_pasted_layout_reference(source, 'html', '', 1, self.db)
            fetch.assert_not_awaited()
            self.assertIn('color:#123456', ref.html_template)
            for value in ['<script', '<iframe', 'onclick', '127.0.0.1', 'file:///']:
                self.assertNotIn(value, ref.html_template)

    async def test_valid_data_images_are_retained(self):
        source = '<p>正文<img src="data:image/png;base64,' + base64.b64encode(PNG).decode() + '"></p>'
        ref = await create_pasted_layout_reference(source, 'html', '', 1, self.db)
        self.assertEqual(len(ref.assets), 1)
        self.assertIn('layout-reference://', ref.html_template)

    async def test_limits(self):
        for content, fmt in [('', 'text'), ('a' * (5*1024*1024+1), 'html'), ('正文', 'other')]:
            with self.assertRaises(LayoutReferenceError):
                await create_pasted_layout_reference(content, fmt, '', 1, self.db)

    @contextmanager
    def image_transport(self, handler):
        real_client = httpx.AsyncClient
        async def resolve(host, *_args, **_kwargs):
            address = '10.0.0.1' if host == 'private.example' else '93.184.216.34'
            return [(2, 1, 6, '', (address, 443))]
        with (patch('app.services.layout_reference.httpx.AsyncClient',
                    side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)),
              patch.object(asyncio.get_running_loop(), 'getaddrinfo', new=AsyncMock(side_effect=resolve))):
            yield

    async def test_download_opt_in_persists_and_rewrites_public_images_only(self):
        source = '<p>正文<img src="https://images.example/photo.png"><img src="https://images.example/photo.png"></p><section style="background-image:url(//images.example/bg.png)">背景</section><svg><image href="http://images.example/svg.png"></image></svg>'
        requests = []
        def handler(request):
            requests.append(str(request.url))
            self.assertNotIn('cookie', request.headers)
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, content=PNG)
        with self.image_transport(handler):
            payload = await paste_layout_reference(
                LayoutReferencePasteRequest(content=source, download_external_images=True), SimpleNamespace(id=1), self.db)
        self.assertEqual(len(requests), 3)
        self.assertIn('https://images.example/bg.png', requests)
        self.assertIn('http://images.example/svg.png', requests)
        self.assertEqual(payload['summary']['image_assets'], 3)
        self.assertIsNone(payload['warning'])
        self.assertNotIn('images.example', payload['preview_html'])
        self.assertIn('/api/layout-references/', payload['preview_html'])
        ref = get_layout_reference(self.db, payload['reference_id'], 1)
        self.assertEqual(len(ref.assets), 3)
        self.assertEqual(ref.assets[0].usage_count, 2)
        self.assertTrue(all(asset.data == PNG for asset in ref.assets))
        # Transfer does not bypass asset selection or reuse authorization.
        self.assertFalse(ref.assets[0].default_selected)
        self.assertTrue(payload['requires_asset_reuse_confirmation'])

    async def test_unavailable_and_unsafe_images_do_not_discard_successful_layout(self):
        urls = ['https://images.example/ok.png', 'https://images.example/missing.png',
                'https://images.example/not-image', 'https://images.example/redirect',
                'https://127.0.0.1/secret', 'https://private.example/secret',
                'file:///secret', '/relative.png', 'blob:https://example/a']
        source = '<p>保留正文</p>' + ''.join(f'<img src="{url}">' for url in urls)
        requests = []
        def handler(request):
            requests.append(str(request.url))
            if request.url.path == '/redirect':
                return httpx.Response(302, headers={'location': 'https://127.0.0.1/secret'})
            if request.url.path == '/missing.png':
                return httpx.Response(404)
            return httpx.Response(200, content=b'not an image' if request.url.path == '/not-image' else PNG)
        with self.image_transport(handler):
            ref = await create_pasted_layout_reference(source, 'html', '', 1, self.db, download_external_images=True)
        self.assertEqual(len(requests), 4)
        self.assertTrue(all(url.startswith('https://images.example/') for url in requests))
        self.assertEqual(len(ref.assets), 1)
        self.assertIn('保留正文', ref.html_template)
        self.assertIn('已转存 1 个', ref.warning)
        self.assertIn('8 个地址', ref.warning)
        self.assertEqual(ref.html_template.count('layout-reference://'), 1)
        for value in ['images.example', '127.0.0.1', 'private.example', 'file://', 'blob:', '/relative.png']:
            self.assertNotIn(value, ref.preview_payload()['preview_html'])

    async def test_default_does_not_fetch_external_images(self):
        payload = LayoutReferencePasteRequest(content='<p>正文<img src="https://images.example/a.png"></p>')
        self.assertFalse(payload.download_external_images)
        with patch('app.services.layout_reference.fetch_public_image', new_callable=AsyncMock) as fetch:
            preview = await paste_layout_reference(payload, SimpleNamespace(id=1), self.db)
        fetch.assert_not_awaited()
        self.assertEqual(preview['assets'], [])
        self.assertIn('转存外部图片', preview['warning'])

    async def test_combined_remote_and_embedded_byte_limit(self):
        source = '<p>正文<img src="data:image/png;base64,' + base64.b64encode(PNG).decode() + '"><img src="https://images.example/a.png"></p>'
        with (self.image_transport(lambda _request: httpx.Response(200, content=PNG)),
              patch('app.services.layout_reference.MAX_REFERENCE_IMAGE_TOTAL_BYTES', len(PNG) * 2 - 1)):
            with self.assertRaisesRegex(LayoutReferenceError, '总大小'):
                await create_pasted_layout_reference(source, 'html', '', 1, self.db, download_external_images=True)

    async def test_remote_downloads_are_bounded_and_duplicates_are_fetched_once(self):
        active, peak, calls = 0, 0, []
        async def handler(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            calls.append(str(request.url))
            await asyncio.sleep(.001)
            active -= 1
            return httpx.Response(200, content=PNG)
        source = '<p>正文</p>' + ''.join(f'<img src="https://images.example/{i % 8}.png">' for i in range(16))
        with self.image_transport(handler):
            ref = await create_pasted_layout_reference(source, 'html', '', 1, self.db, download_external_images=True)
        self.assertEqual(len(calls), 8)
        self.assertLessEqual(peak, 4)
        self.assertEqual(len(ref.assets), 8)

    async def test_cancelling_parse_stops_downloads_and_does_not_persist_a_reference(self):
        from app.models.chat_layout_reference import ChatLayoutReference
        started = asyncio.Event()
        active = 0
        async def fetch(*_args, **_kwargs):
            nonlocal active
            active += 1
            if active == 4:
                started.set()
            try:
                await asyncio.Future()
            finally:
                active -= 1
        source = '<p>正文</p>' + ''.join(f'<img src="https://images.example/{i}.png">' for i in range(12))
        with patch('app.services.layout_reference.fetch_public_image', new=fetch):
            task = asyncio.create_task(create_pasted_layout_reference(source, 'html', '', 1, self.db, download_external_images=True))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertEqual(active, 0)
        self.assertEqual(self.db.query(ChatLayoutReference).count(), 0)
