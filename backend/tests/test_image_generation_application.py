from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from typing import Any, AsyncIterator, Sequence
from unittest.mock import MagicMock, patch

from app.api.routes.image_generations import apply_document_generated_image
from app.models.document import Document
from app.models.image_generation import GeneratedImageAsset, ImageGeneration, ImageGenerationPurpose, ImageGenerationStatus
from app.schemas.image_generation import ImageGenerationApply
from app.services.chat_agent import HtmlEditSession, _take_matching_tool_report, run_agent_loop
from app.services.html_workspace import HtmlWorkspace
from app.services.tool_output_store import ToolOutputStore
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk


class _ScriptedToolModel(BaseChatModel):
    script: list[dict[str, Any]] = []
    seen_messages: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-image-application"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "_ScriptedToolModel":
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

    def test_agent_can_apply_cover_candidate_as_body_and_checkpoint_html(self) -> None:
        source_html = "<section><h1>文章标题</h1><p>正文内容</p></section>"
        workspace = HtmlWorkspace(source_html)
        heading = next(block for block in workspace.map_payload()["blocks"] if block["tag"] == "h1")
        checkpointed_html: list[str] = []
        session = HtmlEditSession(source_html, checkpoint_callback=checkpointed_html.append)
        asset = SimpleNamespace(
            id="asset-1",
            generation_id="generation-1",
            url="https://cdn.example.test/banner.png",
            is_applied=False,
            applied_at=None,
        )
        generation = SimpleNamespace(
            id="generation-1",
            document_id=1,
            user_id=7,
            purpose=ImageGenerationPurpose.COVER,
            status=ImageGenerationStatus.SUCCEEDED,
            prompt="横幅配图",
        )
        document = SimpleNamespace(id=1)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = generation

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
                        "apply_generated_image",
                        {
                            "generation_id": generation.id,
                            "asset_id": asset.id,
                            "target": "body",
                            "revision": workspace.revision,
                            "anchor_block_id": heading["block_id"],
                            "expected_hash": heading["expected_hash"],
                        },
                    )
                },
                {"text": "横幅已插入标题之后。"},
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
                    "将图片插入标题之后",
                    workspace.map_payload(),
                    None,
                    [],
                    session=session,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=1, run_id="image-application-test"),
                    actor_user_id=7,
                    image_generation_context={"explicit_requested": True},
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", return_value=db),
            patch("app.services.chat_agent.tool_output_stats", return_value={"count": 0, "total_bytes": 0, "total_tokens": 0}),
        ):
            events = asyncio.run(run())

        result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_generated_image"
        )
        self.assertEqual(result["activity"]["kind"], "image_application")
        self.assertIn("banner.png", result["html"])
        self.assertTrue(asset.is_applied)
        self.assertEqual(checkpointed_html, [session.html])
        self.assertIn("banner.png", session.html)
        db.commit.assert_called_once()

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
                )
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
