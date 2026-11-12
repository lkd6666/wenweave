from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from typing import Any, AsyncIterator, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes.image_generations import apply_document_generated_image
from app.models.document import Document
from app.models.image_generation import GeneratedImageAsset, ImageGeneration, ImageGenerationOperation, ImageGenerationPurpose, ImageGenerationStatus
from app.schemas.image_generation import ImageGenerationApply
from app.services.chat_agent import HtmlEditSession, _take_matching_tool_report, run_agent_loop
from app.services.html_workspace import HtmlWorkspace
from app.services.document_images import StoredDocumentImage
from app.services.image_generation import cover_source_fingerprint, image_source_at, image_target_fingerprint, materialize_source_image, replace_image_source
from app.services.image_search import ImageSearchCandidate
from app.services.tool_output_store import ToolOutputStore
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk


class _ScriptedToolModel(BaseChatModel):
    script: list[dict[str, Any]] = []
    seen_messages: list[list[BaseMessage]] = []
    bound_tool_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-image-application"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "_ScriptedToolModel":
        self.bound_tool_names = [item.name for item in tools]
        return self

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.seen_messages.append(list(messages))
        step = self.script[min(len(self.seen_messages) - 1, len(self.script) - 1)]
        if step.get("text"):
            yield ChatGenerationChunk(message=AIMessageChunk(content=step["text"]))
        if step.get("tool"):
            name, arguments = step["tool"]
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": name,
                            "id": f"call-{len(self.seen_messages)}",
                            "args": json.dumps(arguments, ensure_ascii=False),
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )
        for index, (name, arguments) in enumerate(step.get("tools", [])):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": name,
                            "id": f"call-{len(self.seen_messages)}-{index}",
                            "args": json.dumps(arguments, ensure_ascii=False),
                            "index": index,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )

    def _generate(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - this test uses streaming only.
        raise NotImplementedError


class ImageGenerationApplicationTests(unittest.TestCase):
    def test_source_image_reads_configured_storage_without_public_fetch(self) -> None:
        storage = SimpleNamespace(endpoint="oss-cn-example.aliyuncs.com", bucket="article-images", custom_domain="")
        source_url = "https://article-images.oss-cn-example.aliyuncs.com/yibanpaiban%2F20260808%2Foriginal.png?Expires=1"
        image_info = SimpleNamespace(content_type="image/png")

        async def run() -> tuple[bytes, str]:
            with (
                patch("app.services.image_generation.oss_client.storage_object_key_for_url", return_value="yibanpaiban/20260808/original.png"),
                patch("app.services.image_generation.oss_client.get_object_bytes", return_value=b"png-bytes"),
                patch("app.services.image_generation.local_uploads.inspect_image", return_value=image_info),
            ):
                return await materialize_source_image(source_url, storage=storage)

        data, content_type = asyncio.run(run())
        self.assertEqual(data, b"png-bytes")
        self.assertEqual(content_type, "image/png")

    def test_signed_image_url_accepts_html_entity_encoding(self) -> None:
        source_url = "https://cdn.example.test/image.png?Expires=2101&Signature=abc%2F123"
        source_html = '<p><img src="https://cdn.example.test/image.png?Expires=2101&amp;Signature=abc%2F123" alt="原图"></p>'

        self.assertTrue(image_target_fingerprint(source_html, 0, source_url))
        replaced = replace_image_source(source_html, 0, source_url, "https://cdn.example.test/replaced.png")
        self.assertIn('src="https://cdn.example.test/replaced.png"', replaced)

    def test_svg_image_sources_use_the_same_replacement_slots(self) -> None:
        source_url = "https://cdn.example.test/lab.png"
        source_html = (
            '<section><svg><image href="https://cdn.example.test/other.png" />'
            f'<image xlink:href="{source_url}" /></svg></section>'
        )

        self.assertEqual(image_source_at(source_html, 1), source_url)
        self.assertTrue(image_target_fingerprint(source_html, 1, source_url))
        replaced = replace_image_source(source_html, 1, source_url, "https://cdn.example.test/replaced.png")
        self.assertIn('xlink:href="https://cdn.example.test/replaced.png"', replaced)

    def test_svg_image_replacement_keeps_href_and_xlink_in_sync(self) -> None:
        source_url = "https://cdn.example.test/original.png"
        next_url = "https://cdn.example.test/replaced.png"
        source_html = (
            '<svg><image xlink:href="https://cdn.example.test/legacy.png" '
            f'href="{source_url}" data-href="keep-me" /></svg>'
        )

        self.assertEqual(image_source_at(source_html, 0), source_url)
        replaced = replace_image_source(source_html, 0, source_url, next_url)
        self.assertIn(f'href="{next_url}"', replaced)
        self.assertIn(f'xlink:href="{next_url}"', replaced)
        self.assertIn('data-href="keep-me"', replaced)

    def test_svg_image_empty_href_uses_xlink_source(self) -> None:
        source_url = "https://cdn.example.test/original.png"
        source_html = f'<svg><image href="" xlink:href="{source_url}" /></svg>'

        self.assertEqual(image_source_at(source_html, 0), source_url)
        replaced = replace_image_source(source_html, 0, source_url, "https://cdn.example.test/replaced.png")
        self.assertEqual(replaced.count('https://cdn.example.test/replaced.png'), 2)

    def test_regular_candidate_can_replace_explicit_image_target(self) -> None:
        source_url = "/api/documents/local-images/original.png"
        source_html = f'<section><img src="{source_url}" alt="原图" style="width:66%"></section>'
        workspace = HtmlWorkspace(source_html)
        document = SimpleNamespace(id=1, current_html=source_html)
        asset = SimpleNamespace(id="asset-1", url="https://cdn.example.test/candidate.png", is_applied=False, applied_at=None)
        generation = SimpleNamespace(
            purpose=ImageGenerationPurpose.BODY,
            operation=ImageGenerationOperation.GENERATE,
            status=ImageGenerationStatus.SUCCEEDED,
            prompt="候选图片",
            target_image_index=-1,
            source_image_url="",
            source_image_hash="",
            assets=[asset],
        )
        payload = ImageGenerationApply(
            target="body",
            revision=workspace.revision,
            source_image_url=source_url,
            target_image_index=0,
        )
        db = MagicMock()

        with (
            patch("app.api.routes.image_generations._generation_or_404", return_value=generation),
            patch("app.api.routes.image_generations._document_or_404", return_value=document),
            patch("app.api.routes.image_generations._require_idle_document"),
            patch("app.api.routes.image_generations.touch_document"),
            patch("app.api.routes.image_generations.create_document_version"),
            patch("app.api.routes.image_generations.generation_payload", return_value={"id": "generation-1"}),
        ):
            apply_document_generated_image(1, "generation-1", asset.id, payload, SimpleNamespace(id=1), db)

        self.assertIn('src="https://cdn.example.test/candidate.png"', document.current_html)
        self.assertIn('style="width:66%"', document.current_html)

    def test_replace_candidate_preserves_current_image_markup(self) -> None:
        source_html = '<section><p><img src="/api/documents/local-images/original.png" alt="原图" style="width:66%" data-crop-source="x" /></p></section>'
        workspace = HtmlWorkspace(source_html)
        source_url = "/api/documents/local-images/original.png"
        document = SimpleNamespace(id=1, current_html=source_html)
        asset = SimpleNamespace(id="asset-1", url="https://cdn.example.test/replaced.png", is_applied=False, applied_at=None)
        generation = SimpleNamespace(
            purpose=ImageGenerationPurpose.BODY,
            operation=ImageGenerationOperation.GENERATE,
            status=ImageGenerationStatus.SUCCEEDED,
            prompt="替换图片",
            target_image_index=0,
            source_image_url=source_url,
            source_image_hash=image_target_fingerprint(source_html, 0, source_url),
            assets=[asset],
        )
        payload = ImageGenerationApply(
            target="body",
            revision=workspace.revision,
            source_image_url=source_url,
            source_image_hash=generation.source_image_hash,
            target_image_index=0,
        )
        db = MagicMock()
        with (
            patch("app.api.routes.image_generations._generation_or_404", return_value=generation),
            patch("app.api.routes.image_generations._document_or_404", return_value=document),
            patch("app.api.routes.image_generations._require_idle_document"),
            patch("app.api.routes.image_generations.touch_document"),
            patch("app.api.routes.image_generations.create_document_version"),
            patch("app.api.routes.image_generations.generation_payload", return_value={"id": "generation-1"}),
        ):
            apply_document_generated_image(1, "generation-1", asset.id, payload, SimpleNamespace(id=1), db)

        self.assertIn('src="https://cdn.example.test/replaced.png"', document.current_html)
        self.assertIn('style="width:66%"', document.current_html)
        self.assertIn('data-crop-source="x"', document.current_html)
        self.assertNotIn(source_url, document.current_html)
        self.assertTrue(asset.is_applied)

    def test_cover_candidate_can_be_explicitly_reused_as_body_banner(self) -> None:
        source_html = "<section><h1>文章标题</h1><p>正文内容</p></section>"
        workspace = HtmlWorkspace(source_html)
        heading = next(block for block in workspace.map_payload()["blocks"] if block["tag"] == "h1")
        document = SimpleNamespace(id=1, current_html=source_html)
        asset = SimpleNamespace(
            id="asset-1",
            url="https://cdn.example.test/banner.png",
            is_applied=False,
            applied_at=None,
        )
        generation = SimpleNamespace(
            purpose=ImageGenerationPurpose.COVER,
            status=ImageGenerationStatus.SUCCEEDED,
            prompt="横幅配图",
            assets=[asset],
        )
        payload = ImageGenerationApply(
            target="body",
            revision=workspace.revision,
            anchor_block_id=heading["block_id"],
            expected_hash=heading["expected_hash"],
        )
        db = MagicMock()

        with (
            patch("app.api.routes.image_generations._generation_or_404", return_value=generation),
            patch("app.api.routes.image_generations._document_or_404", return_value=document),
            patch("app.api.routes.image_generations._require_idle_document"),
            patch("app.api.routes.image_generations.touch_document"),
            patch("app.api.routes.image_generations.create_document_version"),
            patch("app.api.routes.image_generations.generation_payload", return_value={"id": "generation-1"}),
        ):
            result = apply_document_generated_image(
                1,
                "generation-1",
                asset.id,
                payload,
                SimpleNamespace(id=1),
                db,
            )

        self.assertEqual(result, {"id": "generation-1"})
        self.assertTrue(asset.is_applied)
        self.assertIsNotNone(asset.applied_at)
        self.assertIn('src="https://cdn.example.test/banner.png"', document.current_html)
        self.assertLess(document.current_html.index("</h1>"), document.current_html.index("banner.png"))
        db.commit.assert_called_once()

    def test_agent_uses_html_patch_to_place_generated_candidate_in_nested_container(self) -> None:
        source_html = (
            '<section class="article"><h1>文章标题</h1>'
            '<div class="feature-card"><p>这里保留卡片导语。</p></div>'
            '<p>正文内容</p></section>'
        )
        workspace = HtmlWorkspace(source_html)
        card = next(block for block in workspace.map_payload()["blocks"] if block["attributes"] == 'class="feature-card"')
        checkpointed_html: list[str] = []
        session = HtmlEditSession(source_html, checkpoint_callback=checkpointed_html.append)
        model = _ScriptedToolModel(
            script=[
                {"tool": ("read_blocks", {"block_ids": [card["block_id"]]})},
                {
                    "tool": (
                        "apply_html_patch",
                        {
                            "revision": workspace.revision,
                            "operations": [
                                {
                                    "block_id": card["block_id"],
                                    "expected_hash": card["expected_hash"],
                                    "mode": "replace_inner",
                                    "html": (
                                        '<figure class="feature-image">'
                                        '<img src="https://cdn.example.test/banner.png" alt="AI 生成横幅" />'
                                        '<figcaption>卡片配图</figcaption></figure>'
                                    ),
                                }
                            ],
                        },
                    )
                },
                {"text": "已将生成候选放入文章特色卡片。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "生成一张横幅并放进特色卡片容器",
                    workspace.map_payload(),
                    None,
                    [],
                    session=session,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="generated-image-patch-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}):
            events = asyncio.run(run())

        result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_html_patch"
        )
        self.assertEqual(result["activity"]["kind"], "edit")
        self.assertIn("banner.png", result["html"])
        self.assertEqual(checkpointed_html, [session.html])
        self.assertIn("banner.png", session.html)
        self.assertIn('class="feature-card"><figure', session.html)
        self.assertNotIn('class="feature-card"><p>', session.html)
        self.assertNotIn("apply_generated_image", model.bound_tool_names)
        self.assertIn("apply_generated_cover", model.bound_tool_names)

    def test_agent_imports_searched_candidate_then_patches_nested_container(self) -> None:
        source_html = (
            '<section class="article"><h1>文章标题</h1>'
            '<div class="feature-card"><p>这里保留卡片导语。</p></div>'
            '<p>正文内容</p></section>'
        )
        workspace = HtmlWorkspace(source_html)
        card = next(block for block in workspace.map_payload()["blocks"] if block["attributes"] == 'class="feature-card"')
        session = HtmlEditSession(source_html)
        candidate = ImageSearchCandidate(
            id="searched-card-1",
            image_url="https://images.example.test/card.jpg",
            preview_url="https://images.example.test/card-preview.jpg",
            source_page_url="https://example.test/card",
            title="城市公园晨光",
            engine="search",
            width=1600,
            height=900,
            image_format="jpeg",
        )
        stored = StoredDocumentImage(
            url="/api/documents/local-images/searched-card.jpg",
            object_key="manual/searched-card.jpg",
            storage_mode="local",
        )
        library_asset = SimpleNamespace(id="library-search-card-1")
        db = MagicMock()
        model = _ScriptedToolModel(
            script=[
                {"tool": ("import_searched_image", {"candidate_ref": "searched-candidate-ref"})},
                {"tool": ("read_blocks", {"block_ids": [card["block_id"]]})},
                {
                    "tool": (
                        "apply_html_patch",
                        {
                            "revision": workspace.revision,
                            "operations": [
                                {
                                    "block_id": card["block_id"],
                                    "expected_hash": card["expected_hash"],
                                    "mode": "replace_inner",
                                    "html": (
                                        '<figure class="feature-image">'
                                        '<img src="/api/documents/local-images/searched-card.jpg" alt="城市公园晨光" />'
                                        '<figcaption>城市公园晨光</figcaption></figure>'
                                    ),
                                }
                            ],
                        },
                    )
                },
                {"text": "已将导入的搜索图片放入文章特色卡片。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "找一张城市公园图片，放进特色卡片",
                    workspace.map_payload(),
                    None,
                    [],
                    session=session,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="searched-image-patch-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.image_search.decode_candidate_reference_or_token", return_value=candidate),
            patch("app.services.image_search.fetch_candidate_image", new=AsyncMock(return_value=(b"image", SimpleNamespace(content_type="image/jpeg", width=1600, height=900)))),
            patch("app.services.document_images.store_tracked_document_image", return_value=stored),
            patch("app.services.image_library.create_library_asset", return_value=library_asset),
        ):
            events = asyncio.run(run())

        imported = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "import_searched_image"
        )
        patched = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_html_patch"
        )
        self.assertEqual(imported["activity"]["kind"], "image_import")
        self.assertEqual(imported["activity"]["details"]["url"], stored.url)
        self.assertEqual(patched["activity"]["kind"], "edit")
        self.assertIn("import_searched_image", model.bound_tool_names)
        self.assertNotIn("apply_searched_image", model.bound_tool_names)
        self.assertIn('class="feature-card"><figure', session.html)
        self.assertIn(stored.url, session.html)
        self.assertNotIn('class="feature-card"><p>', session.html)

    def test_agent_can_set_imported_searched_asset_as_cover_only(self) -> None:
        source_html = "<section><p>正文保持不变</p></section>"
        workspace = HtmlWorkspace(source_html)
        asset = SimpleNamespace(
            id="library-search-cover-1",
            owner_id=7,
            document_id=1,
            url="/api/documents/local-images/search-cover.jpg",
            source="search",
            deleted_at=None,
        )
        document = SimpleNamespace(
            id=1,
            wechat_cover_url="",
            wechat_pic_crop_235_1="stale-crop",
            wechat_pic_crop_1_1="stale-square-crop",
        )
        db = MagicMock()

        class _Query:
            def __init__(self, value: Any) -> None:
                self.value = value
            def filter(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def populate_existing(self) -> "_Query":
                return self
            def with_for_update(self) -> "_Query":
                return self
            def first(self) -> Any:
                return self.value

        db.query.side_effect = lambda model: _Query(asset if model.__name__ == "ImageLibraryAsset" else document)
        model = _ScriptedToolModel(
            script=[
                {"tool": ("apply_searched_cover", {"asset_id": asset.id})},
                {"text": "已将搜索图片设为文章封面。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "将搜索图片设为封面",
                    workspace.map_payload(),
                    None,
                    [],
                    session=HtmlEditSession(source_html),
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="searched-cover-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.chat_agent.touch_document") as touch,
            patch("app.services.chat_agent.create_document_version") as create_version,
        ):
            events = asyncio.run(run())

        result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_searched_cover"
        )
        self.assertEqual(result["activity"]["details"]["target"], "cover")
        self.assertEqual(document.wechat_cover_url, asset.url)
        self.assertEqual(document.wechat_pic_crop_235_1, "")
        self.assertEqual(document.wechat_pic_crop_1_1, "")
        self.assertEqual(model.bound_tool_names.count("apply_searched_cover"), 1)
        touch.assert_called_once_with(document, 7)
        create_version.assert_called_once()
        db.commit.assert_called_once()

    def test_agent_rejects_unavailable_searched_cover_asset(self) -> None:
        source_html = "<section><p>正文保持不变</p></section>"
        workspace = HtmlWorkspace(source_html)
        db = MagicMock()

        class _Query:
            def filter(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def first(self) -> None:
                return None

        db.query.return_value = _Query()
        model = _ScriptedToolModel(
            script=[
                {"tool": ("apply_searched_cover", {"asset_id": "foreign-or-generated-asset"})},
                {"text": "该素材不可用。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "设为封面",
                    workspace.map_payload(),
                    None,
                    [],
                    session=HtmlEditSession(source_html),
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="searched-cover-unavailable-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
        ):
            events = asyncio.run(run())

        error = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_searched_cover"
        )
        self.assertIn("搜索图片素材不存在或不可用", error["result"])
        db.commit.assert_not_called()

    def test_agent_can_retry_generated_candidate_patch_after_stale_hash(self) -> None:
        source_html = '<section><div class="feature-card"><p>正文内容</p></div></section>'
        workspace = HtmlWorkspace(source_html)
        card = next(block for block in workspace.map_payload()["blocks"] if block["attributes"] == 'class="feature-card"')
        session = HtmlEditSession(source_html)
        model = _ScriptedToolModel(
            script=[
                {
                    "tool": (
                        "apply_html_patch",
                        {
                            "revision": workspace.revision,
                            "operations": [{
                                "block_id": card["block_id"],
                                "expected_hash": "stale-hash",
                                "mode": "replace_inner",
                                "html": '<img src="https://cdn.example.test/retry.png" alt="重试候选" />',
                            }],
                        },
                    )
                },
                {"tool": ("read_blocks", {"block_ids": [card["block_id"]]})},
                {
                    "tool": (
                        "apply_html_patch",
                        {
                            "revision": workspace.revision,
                            "operations": [{
                                "block_id": card["block_id"],
                                "expected_hash": card["expected_hash"],
                                "mode": "replace_inner",
                                "html": '<img src="https://cdn.example.test/retry.png" alt="重试候选" />',
                            }],
                        },
                    )
                },
                {"text": "已重新读取卡片容器并应用生成候选。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "将候选图放入特色卡片",
                    workspace.map_payload(),
                    None,
                    [],
                    session=session,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="generated-image-patch-retry-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}):
            events = asyncio.run(run())

        applications = [
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_html_patch"
        ]
        self.assertEqual(len(applications), 2)
        self.assertIn("基于旧内容", applications[0]["result"])
        self.assertEqual(applications[0]["activity"]["details"]["current_revision"], workspace.revision)
        self.assertEqual(applications[0]["activity"]["details"]["current_block"]["block_id"], card["block_id"])
        self.assertEqual(applications[1]["activity"]["kind"], "edit")
        self.assertIn("retry.png", session.html)

    def test_agent_can_set_its_successful_candidate_as_cover_only(self) -> None:
        source_html = "<section><p>正文保持不变</p></section>"
        workspace = HtmlWorkspace(source_html)
        session = HtmlEditSession(source_html)
        asset = SimpleNamespace(
            id="asset-cover-1",
            generation_id="generation-cover-1",
            url="https://cdn.example.test/cover.png",
            is_applied=False,
            applied_at=None,
        )
        generation = SimpleNamespace(
            id="generation-cover-1",
            document_id=1,
            user_id=7,
            status=ImageGenerationStatus.SUCCEEDED,
        )
        document = SimpleNamespace(
            id=1,
            wechat_cover_url="",
            wechat_pic_crop_235_1="stale-crop",
            wechat_pic_crop_1_1="stale-square-crop",
        )
        db = MagicMock()
        def query(model):
            result = MagicMock()
            result.filter.return_value = result
            result.populate_existing.return_value = result
            result.with_for_update.return_value = result
            result.first.return_value = document if model is Document else generation
            return result
        db.query.side_effect = query

        def get_item(model: Any, item_id: Any) -> Any:
            if model is GeneratedImageAsset and item_id == asset.id:
                return asset
            if model is Document and item_id == document.id:
                return document
            return None

        db.get.side_effect = get_item
        model = _ScriptedToolModel(
            script=[
                {"tool": ("apply_generated_cover", {"generation_id": generation.id, "asset_id": asset.id})},
                {"text": "已将生成候选设为文章封面。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "将生成图设为封面",
                    workspace.map_payload(),
                    None,
                    [],
                    session=session,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="generated-cover-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.chat_agent.touch_document") as touch,
            patch("app.services.chat_agent.create_document_version") as create_version,
        ):
            events = asyncio.run(run())

        result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_generated_cover"
        )
        self.assertEqual(result["activity"]["details"]["target"], "cover")
        self.assertEqual(document.wechat_cover_url, asset.url)
        self.assertEqual(document.wechat_pic_crop_235_1, "")
        self.assertEqual(document.wechat_pic_crop_1_1, "")
        self.assertTrue(asset.is_applied)
        self.assertIsNotNone(asset.applied_at)
        self.assertEqual(session.html, source_html)
        touch.assert_called_once_with(document, 7)
        create_version.assert_called_once()
        db.commit.assert_called_once()

    def test_agent_rejects_generated_cover_from_another_user(self) -> None:
        source_html = "<section><p>正文保持不变</p></section>"
        workspace = HtmlWorkspace(source_html)
        asset = SimpleNamespace(id="asset-cover-foreign", generation_id="generation-cover-foreign", url="https://cdn.example.test/foreign.png")
        generation = SimpleNamespace(
            id="generation-cover-foreign",
            document_id=1,
            user_id=99,
            status=ImageGenerationStatus.SUCCEEDED,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = generation
        db.get.return_value = asset
        model = _ScriptedToolModel(
            script=[
                {"tool": ("apply_generated_cover", {"generation_id": generation.id, "asset_id": asset.id})},
                {"text": "候选不可用。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "将生成图设为封面",
                    workspace.map_payload(),
                    None,
                    [],
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="generated-cover-foreign-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
        ):
            events = asyncio.run(run())

        error = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_generated_cover"
        )
        self.assertIn("图片候选不可用", error["result"])
        db.commit.assert_not_called()

    def test_agent_can_apply_edited_image_without_explicit_confirmation(self) -> None:
        source_url = "/api/documents/local-images/original.png"
        source_html = f'<section><img src="{source_url}" alt="原图"></section>'
        workspace = HtmlWorkspace(source_html)
        checkpointed_html: list[str] = []
        session = HtmlEditSession(source_html, checkpoint_callback=checkpointed_html.append)
        asset = SimpleNamespace(
            id="asset-edit-1",
            generation_id="generation-edit-1",
            url="https://cdn.example.test/edited.png",
            is_applied=False,
            applied_at=None,
        )
        generation = SimpleNamespace(
            id="generation-edit-1",
            document_id=1,
            user_id=7,
            status=ImageGenerationStatus.SUCCEEDED,
            operation=ImageGenerationOperation.EDIT,
            target_image_index=0,
            source_image_url=source_url,
            source_image_hash=image_target_fingerprint(source_html, 0, source_url),
        )
        document = SimpleNamespace(id=1, current_html=source_html)
        db = MagicMock()
        def query(model):
            result = MagicMock()
            result.filter.return_value = result
            result.populate_existing.return_value = result
            result.with_for_update.return_value = result
            result.first.return_value = document if model is Document else generation
            return result
        db.query.side_effect = query

        def get_item(model: Any, item_id: Any) -> Any:
            if model is GeneratedImageAsset and item_id == asset.id:
                return asset
            if model is Document and item_id == document.id:
                return document
            return None

        db.get.side_effect = get_item
        model = _ScriptedToolModel(
            script=[
                {
                    "tool": (
                        "apply_edited_image",
                        {
                            "generation_id": generation.id,
                            "asset_id": asset.id,
                            "revision": workspace.revision,
                        },
                    )
                },
                {"text": "已按任务目标替换图片。"},
            ],
            seen_messages=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "自动优化文章图片",
                    workspace.map_payload(),
                    None,
                    [],
                    session=session,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="edited-image-test"),
                    actor_user_id=7,
                    image_generation_context={"explicit_requested": False},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.chat_agent.touch_document"),
            patch("app.services.chat_agent.create_document_version"),
        ):
            events = asyncio.run(run())

        result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_edited_image"
        )
        self.assertEqual(result["activity"]["kind"], "image_application")
        self.assertIn("edited.png", session.html)
        self.assertEqual(checkpointed_html, [session.html])
        self.assertTrue(asset.is_applied)

    def test_agent_bakes_body_transform_and_clears_stale_image_variants(self) -> None:
        source_url = "/api/documents/local-images/original.png"
        source_html = (
            f'<section class="hero"><img src="{source_url}" alt="原图" style="width:66%" '
            'srcset="original-2x.png 2x" sizes="66vw" data-crop-source="older.png" '
            'data-crop-rect="0,0,100000,100000" data-crop-rotation="90" '
            'data-preview-upload-id="preview-1"></section>'
        )
        workspace = HtmlWorkspace(source_html)
        image_fingerprint = workspace.image_inventory()["images"][0]["source_fingerprint"]
        checkpointed_html: list[str] = []
        session = HtmlEditSession(source_html, checkpoint_callback=checkpointed_html.append)
        document = SimpleNamespace(id=1, current_html=source_html)
        stored = StoredDocumentImage(
            url="/api/documents/local-images/transformed.png",
            object_key="local/images/transformed.png",
            storage_mode="local",
        )
        db = MagicMock()

        class _Query:
            def __init__(self, value: Any) -> None:
                self.value = value
            def filter(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def populate_existing(self) -> "_Query":
                return self
            def with_for_update(self) -> "_Query":
                return self
            def first(self) -> Any:
                return self.value

        # The transform first looks up storage, then locks the document.
        db.query.side_effect = lambda model: _Query(None if model.__name__ == "StorageConfig" else document)
        model = _ScriptedToolModel(
            script=[
                {
                    "tool": (
                        "transform_document_image",
                        {
                            "target": "article",
                            "image_slot": 1,
                            "revision": workspace.revision,
                            "source_fingerprint": image_fingerprint,
                            "rotation_degrees": 90,
                        },
                    )
                },
                {"text": "图片已裁切并旋转。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "将正文图片右转 90 度",
                    workspace.map_payload(),
                    None,
                    [],
                    session=session,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="transform-body-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        transformed = SimpleNamespace(
            data=b"transformed-png",
            content_type="image/png",
            width=300,
            height=200,
        )
        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.image_generation.materialize_source_image", new=AsyncMock(return_value=(b"source-png", "image/png"))) as materialize,
            patch("app.services.document_image_transform.transform_document_image", return_value=transformed) as bake,
            patch("app.services.document_images.store_tracked_document_image", return_value=stored) as store,
            patch("app.services.chat_agent.touch_document") as touch,
            patch("app.services.chat_agent.create_document_version") as create_version,
        ):
            events = asyncio.run(run())

        result = next(event["data"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "transform_document_image")
        self.assertEqual(result["activity"]["kind"], "image_application")
        self.assertIn('src="/api/documents/local-images/transformed.png"', session.html)
        self.assertIn('alt="原图"', session.html)
        self.assertIn('style="width:66%"', session.html)
        self.assertNotIn("srcset=", session.html)
        self.assertNotIn("sizes=", session.html)
        self.assertNotIn("data-crop-", session.html)
        self.assertNotIn("data-preview-upload-id", session.html)
        self.assertEqual(document.current_html, session.html)
        self.assertEqual(checkpointed_html, [session.html])
        materialize.assert_awaited_once()
        bake.assert_called_once()
        store.assert_called_once()
        touch.assert_called_once_with(document, 7)
        create_version.assert_called_once()
        db.commit.assert_called_once()
        self.assertIn("transform_document_image", model.bound_tool_names)

        from app.services.html_workspace import WorkspaceError
        document.current_html = source_html
        def reject_write(*_args):
            raise WorkspaceError("run ownership lost")
        session = HtmlEditSession(source_html, document_write_guard=reject_write)
        model.seen_messages.clear()
        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.image_generation.materialize_source_image", new=AsyncMock(return_value=(b"source-png", "image/png"))),
            patch("app.services.document_image_transform.transform_document_image", return_value=transformed),
            patch("app.services.document_images.store_tracked_document_image") as late_store,
        ):
            late_events = asyncio.run(run())
        late = next(event["data"] for event in late_events if event["event"] == "tool_result" and event["data"]["name"] == "transform_document_image")
        self.assertEqual(late["activity"]["kind"], "error")
        self.assertIn("run ownership lost", late["result"])
        self.assertEqual(document.current_html, source_html)
        self.assertEqual(session.html, source_html)
        late_store.assert_not_called()

    def test_agent_bakes_cover_transform_and_resets_wechat_crops(self) -> None:
        source_html = "<section><p>正文保持不变</p></section>"
        source_url = "https://cdn.example.test/original-cover.png"
        document = SimpleNamespace(
            id=1,
            current_html=source_html,
            wechat_cover_url=source_url,
            wechat_pic_crop_235_1="cover-crop",
            wechat_pic_crop_1_1="square-crop",
        )
        stored = StoredDocumentImage(
            url="/api/documents/local-images/transformed-cover.png",
            object_key="local/images/transformed-cover.png",
            storage_mode="local",
        )
        db = MagicMock()

        class _Query:
            def __init__(self, value: Any) -> None:
                self.value = value
            def filter(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def populate_existing(self) -> "_Query":
                return self
            def with_for_update(self) -> "_Query":
                return self
            def first(self) -> Any:
                return self.value

        db.query.side_effect = lambda model: _Query(None if model.__name__ == "StorageConfig" else document)
        db.get.side_effect = lambda model, item_id: document if model is Document and item_id == 1 else None
        model = _ScriptedToolModel(
            script=[
                {
                    "tool": (
                        "transform_document_image",
                        {
                            "target": "cover",
                            "source_fingerprint": cover_source_fingerprint(source_url),
                            "rotation_degrees": 90,
                        },
                    )
                },
                {"text": "封面已旋转。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "将封面右转 90 度",
                    HtmlWorkspace(source_html).map_payload(),
                    None,
                    [],
                    session=HtmlEditSession(source_html),
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="transform-cover-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        transformed = SimpleNamespace(
            data=b"transformed-png",
            content_type="image/png",
            width=300,
            height=200,
        )
        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.image_generation.materialize_source_image", new=AsyncMock(return_value=(b"source-png", "image/png"))),
            patch("app.services.document_image_transform.transform_document_image", return_value=transformed),
            patch("app.services.document_images.store_tracked_document_image", return_value=stored),
            patch("app.services.chat_agent.touch_document") as touch,
            patch("app.services.chat_agent.create_document_version") as create_version,
        ):
            events = asyncio.run(run())

        result = next(event["data"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "transform_document_image")
        self.assertEqual(result["activity"]["details"]["target"], "cover")
        self.assertEqual(document.wechat_cover_url, stored.url)
        self.assertEqual(document.wechat_pic_crop_235_1, "")
        self.assertEqual(document.wechat_pic_crop_1_1, "")
        touch.assert_called_once_with(document, 7)
        create_version.assert_called_once()
        db.commit.assert_called_once()

    def test_multimodal_agent_can_view_cover_preview_dimensions_and_fingerprint(self) -> None:
        source_html = "<section><p>正文保持不变</p></section>"
        source_url = "https://cdn.example.test/current-cover.png"
        document = SimpleNamespace(id=1, wechat_cover_url=source_url)
        db = MagicMock()
        db.query.return_value.first.return_value = None
        db.get.return_value = document
        model = _ScriptedToolModel(
            script=[
                {"tool": ("view_article_images", {"references": [{"kind": "cover"}]})},
                {"text": "已读取封面尺寸。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "查看封面尺寸",
                    HtmlWorkspace(source_html).map_payload(),
                    None,
                    [],
                    session=HtmlEditSession(source_html),
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="view-cover-test"),
                    actor_user_id=7,
                    image_generation_context={},
                    model_is_multimodal=True,
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.image_generation.materialize_source_image", new=AsyncMock(return_value=(b"cover-png", "image/png"))),
            patch("app.services.document_image_transform.read_document_image_dimensions", return_value=("image/png", 1200, 628)),
        ):
            events = asyncio.run(run())

        result = next(event["data"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "view_article_images")
        item = result["activity"]["details"]["items"][0]
        self.assertTrue(result["activity"]["details"]["image_content_included"])
        self.assertEqual(result["activity"]["details"]["viewed_count"], 1)
        self.assertEqual(item["preview_url"], source_url)
        self.assertEqual((item["width"], item["height"]), (1200, 628))
        self.assertEqual(item["source_fingerprint"], cover_source_fingerprint(source_url))

    def test_agent_can_apply_edited_cover_and_clears_crop(self) -> None:
        source_html = "<section><p>正文保持不变</p></section>"
        workspace = HtmlWorkspace(source_html)
        source_url = "https://cdn.example.test/original-cover.png"
        asset = SimpleNamespace(
            id="asset-cover-edit-1",
            generation_id="generation-cover-edit-1",
            url="https://cdn.example.test/edited-cover.png",
            is_applied=False,
            applied_at=None,
        )
        generation = SimpleNamespace(
            id="generation-cover-edit-1",
            document_id=1,
            user_id=7,
            status=ImageGenerationStatus.SUCCEEDED,
            operation=ImageGenerationOperation.EDIT,
            purpose=ImageGenerationPurpose.COVER,
            source_image_url=source_url,
            source_image_hash=cover_source_fingerprint(source_url),
        )
        document = SimpleNamespace(
            id=1,
            wechat_cover_url=source_url,
            wechat_pic_crop_235_1="crop",
            wechat_pic_crop_1_1="square-crop",
        )
        db = MagicMock()

        class _Query:
            def __init__(self, value: Any) -> None:
                self.value = value
            def filter(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def populate_existing(self) -> "_Query":
                return self
            def with_for_update(self) -> "_Query":
                return self
            def first(self) -> Any:
                return self.value

        db.query.side_effect = lambda model: _Query(generation if model is ImageGeneration else document)
        db.get.side_effect = lambda model, item_id: asset if model is GeneratedImageAsset else None
        model = _ScriptedToolModel(
            script=[
                {"tool": ("apply_edited_cover", {"generation_id": generation.id, "asset_id": asset.id})},
                {"text": "已更新文章封面。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "编辑文章封面",
                    workspace.map_payload(),
                    None,
                    [],
                    session=HtmlEditSession(source_html),
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="edited-cover-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.chat_agent.touch_document") as touch,
            patch("app.services.chat_agent.create_document_version") as create_version,
        ):
            events = asyncio.run(run())

        result = next(event["data"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "apply_edited_cover")
        self.assertEqual(result["activity"]["kind"], "image_application")
        self.assertEqual(document.wechat_cover_url, asset.url)
        self.assertEqual(document.wechat_pic_crop_235_1, "")
        self.assertEqual(document.wechat_pic_crop_1_1, "")
        self.assertTrue(asset.is_applied)
        self.assertIsNotNone(asset.applied_at)
        touch.assert_called_once_with(document, 7)
        create_version.assert_called_once()
        db.commit.assert_called_once()

    def test_agent_rejects_edited_cover_when_source_changed(self) -> None:
        source_html = "<section><p>正文</p></section>"
        workspace = HtmlWorkspace(source_html)
        original_url = "https://cdn.example.test/original-cover.png"
        document = SimpleNamespace(id=1, wechat_cover_url="https://cdn.example.test/new-cover.png", wechat_pic_crop_235_1="", wechat_pic_crop_1_1="")
        asset = SimpleNamespace(id="asset-stale-cover", generation_id="generation-stale-cover", url="https://cdn.example.test/stale.png", is_applied=False, applied_at=None)
        generation = SimpleNamespace(id="generation-stale-cover", document_id=1, user_id=7, status=ImageGenerationStatus.SUCCEEDED, operation=ImageGenerationOperation.EDIT, purpose=ImageGenerationPurpose.COVER, source_image_url=original_url, source_image_hash=cover_source_fingerprint(original_url))
        db = MagicMock()

        class _Query:
            def filter(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def populate_existing(self) -> "_Query":
                return self
            def with_for_update(self) -> "_Query":
                return self
            def first(self) -> Any:
                return generation if not getattr(self, "document_query", False) else document

        generation_query = _Query(); document_query = _Query(); document_query.document_query = True
        db.query.side_effect = lambda model: generation_query if model is ImageGeneration else document_query
        db.get.side_effect = lambda model, item_id: asset if model is GeneratedImageAsset else None
        model = _ScriptedToolModel(script=[{"tool": ("apply_edited_cover", {"generation_id": generation.id, "asset_id": asset.id})}, {"text": "封面已变化。"}], seen_messages=[], bound_tool_names=[])

        async def run() -> list[dict[str, Any]]:
            return [event async for event in run_agent_loop(model, "测试文章", source_html, "应用封面编辑", workspace.map_payload(), None, [], session=HtmlEditSession(source_html), tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="stale-cover-test"), actor_user_id=7, image_generation_context={}, tool_protocol="v1")]

        with (patch("app.services.chat_agent.SessionLocal", return_value=db), patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0})):
            events = asyncio.run(run())
        error = next(event["data"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "apply_edited_cover")
        self.assertIn("文章封面已发生变化", error["result"])
        self.assertEqual(document.wechat_cover_url, "https://cdn.example.test/new-cover.png")
        self.assertFalse(asset.is_applied)
        db.commit.assert_not_called()

    def test_agent_creates_cover_edit_candidates_from_current_cover(self) -> None:
        source_html = "<section><p>正文</p></section>"
        workspace = HtmlWorkspace(source_html)
        source_url = "https://cdn.example.test/current-cover.png"
        document = SimpleNamespace(id=1, wechat_cover_url=source_url)
        actor = SimpleNamespace(id=7)
        image_model = SimpleNamespace(
            id=5,
            operations=["generate", "edit"],
            provider=SimpleNamespace(image_protocol="openai_images", image_base_url="https://images.example.test/v1"),
        )
        created = SimpleNamespace(id="generation-cover-create")
        completed = SimpleNamespace(id=created.id)
        db = MagicMock()

        class _Query:
            def __init__(self, value: Any) -> None:
                self.value = value
            def options(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def filter(self, *args: Any, **kwargs: Any) -> "_Query":
                return self
            def first(self) -> Any:
                return self.value

        db.get.side_effect = lambda model, item_id: document if model is Document else actor
        db.query.side_effect = lambda model: _Query(image_model if model.__name__ == "AIImageModel" else completed)
        model = _ScriptedToolModel(
            script=[
                {"tool": ("edit_article_cover", {"prompt": "改成暖色的秋日插画封面", "quantity": 2})},
                {"text": "已生成两张封面编辑候选。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "编辑现有封面",
                    workspace.map_payload(),
                    None,
                    [],
                    session=HtmlEditSession(source_html),
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="edited-cover-create-test"),
                    actor_user_id=7,
                    image_generation_context={"image_model_id": 5},
                 tool_protocol="v1")
            ]

        payload = {"id": created.id, "status": "succeeded", "assets": []}
        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
            patch("app.services.image_generation.create_generation", return_value=created) as create_generation,
            patch("app.services.image_generation.run_generation_sync") as run_generation_sync,
            patch("app.services.image_generation.generation_payload", return_value=payload),
            patch("app.services.model_access.can_access_image_model", return_value=True),
        ):
            events = asyncio.run(run())

        result = next(event["data"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "edit_article_cover")
        self.assertEqual(result["activity"]["kind"], "image_generation")
        self.assertIn("edit_article_cover", model.bound_tool_names)
        self.assertIn("apply_edited_cover", model.bound_tool_names)
        kwargs = create_generation.call_args.kwargs
        self.assertEqual(kwargs["purpose"], ImageGenerationPurpose.COVER)
        self.assertEqual(kwargs["operation"], ImageGenerationOperation.EDIT)
        self.assertEqual(kwargs["source_image_url"], source_url)
        self.assertEqual(kwargs["source_image_hash"], cover_source_fingerprint(source_url))
        self.assertEqual(kwargs["target_image_index"], -1)
        self.assertEqual(kwargs["quantity"], 2)
        run_generation_sync.assert_called_once_with(created.id)

    def test_agent_rejects_cover_edit_without_current_cover(self) -> None:
        source_html = "<section><p>正文</p></section>"
        workspace = HtmlWorkspace(source_html)
        document = SimpleNamespace(id=1, wechat_cover_url="")
        db = MagicMock()
        db.get.return_value = document
        model = _ScriptedToolModel(
            script=[
                {"tool": ("edit_article_cover", {"prompt": "修改封面配色"})},
                {"text": "请先设置封面。"},
            ],
            seen_messages=[],
            bound_tool_names=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "编辑现有封面",
                    workspace.map_payload(),
                    None,
                    [],
                    session=HtmlEditSession(source_html),
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="edited-cover-missing-test"),
                    actor_user_id=7,
                    image_generation_context={},
                 tool_protocol="v1")
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
        ):
            events = asyncio.run(run())

        error = next(event["data"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "edit_article_cover")
        self.assertIn("没有可编辑的封面", error["result"])
        db.query.assert_not_called()
        db.commit.assert_not_called()

    def test_parallel_image_generation_reports_match_their_task_ids(self) -> None:
        reports = {
            "generate_article_images": [
                {"activity": {"kind": "image_generation", "details": {"id": "generation-2", "assets": [{"url": "https://cdn.example/2.png"}]}}},
                {"activity": {"kind": "image_generation", "details": {"id": "generation-3", "assets": [{"url": "https://cdn.example/3.png"}]}}},
                {"activity": {"kind": "image_generation", "details": {"id": "generation-1", "assets": [{"url": "https://cdn.example/1.png"}]}}},
            ]
        }
        matched = [
            _take_matching_tool_report(
                "generate_article_images",
                json.dumps({"id": generation_id}),
                reports,
            )
            for generation_id in ("generation-1", "generation-2", "generation-3")
        ]

        self.assertEqual(
            [item["activity"]["details"]["id"] if item else None for item in matched],
            ["generation-1", "generation-2", "generation-3"],
        )
        self.assertEqual(reports["generate_article_images"], [])

    def test_parallel_same_named_tools_keep_their_own_activities(self) -> None:
        source_html = "<section><h1>标题</h1><p>春天的花开了。</p><p>夏天的雨来了。</p><p>秋天的风起了。</p></section>"
        workspace = HtmlWorkspace(source_html)
        model = _ScriptedToolModel(
            script=[
                {
                    "tools": [
                        ("search_html", {"query": "花"}),
                        ("search_html", {"query": "雨"}),
                        ("search_html", {"query": "风"}),
                    ]
                },
                {"text": "已完成三个位置的检索。"},
            ],
            seen_messages=[],
        )

        async def run() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试文章",
                    source_html,
                    "分别检索三个关键词",
                    workspace.map_payload(),
                    None,
                    [],
                 tool_protocol="v1")
            ]

        events = asyncio.run(run())
        results = [
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "search_html"
        ]

        self.assertEqual([item["id"] for item in results], ["call-1-0", "call-1-1", "call-1-2"])
        self.assertEqual([item["activity"]["query"] for item in results], ["花", "雨", "风"])
        self.assertTrue(all(item["activity"]["kind"] == "search" for item in results))


if __name__ == "__main__":
    unittest.main()
