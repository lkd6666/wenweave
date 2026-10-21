"""端到端跑通真实 LangGraph 图：模型 → 工具 → 模型 → 结束。

单元测试只覆盖各个零件（压缩、缓存分块、任务清单校验）。这里用脚本化的假模型
驱动真实图，锁定它们组装起来仍然可用：工具真的改到了 HTML、SSE 事件顺序正确、
run 内压缩不会破坏工具配对导致整轮失败。
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, AsyncIterator, Sequence
from unittest.mock import AsyncMock, patch

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register storage tables for the isolated graph test.
from app.db.base import Base
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.chat_tool_output import ChatToolOutput
from app.services.chat_agent import (
    HtmlEditSession,
    normalise_user_question,
    restore_resume_messages,
    run_agent_loop,
    validate_gzh_theme_candidate,
)
from app.services.html_workspace import HtmlWorkspace
from app.services.image_search import ImageSearchCandidate, decode_candidate_reference
from app.services.tool_output_store import ToolOutputStore

SOURCE_HTML = "<section><h1>旧标题</h1><p>正文内容</p></section>"


class ScriptedChatModel(BaseChatModel):
    """按预设脚本逐轮返回 tool_call 或收尾文本的假模型。"""

    script: list[dict[str, Any]] = []
    seen_message_counts: list[int] = []
    seen_messages: list[list[BaseMessage]] = []
    bound_tool_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        # 脚本已经决定了调用哪个工具，这里只需保持链式调用可用。
        self.bound_tool_names = [str(getattr(tool, "name", "")) for tool in tools]
        return self

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.seen_message_counts.append(len(messages))
        self.seen_messages.append(list(messages))
        step = self.script[min(len(self.seen_message_counts) - 1, len(self.script) - 1)]
        if step.get("text"):
            yield ChatGenerationChunk(message=AIMessageChunk(content=step["text"]))
        if step.get("disconnect_after_text"):
            raise RuntimeError("connection reset by peer")
        tool_steps = step.get("tools") or ([step["tool"]] if step.get("tool") else [])
        for tool_index, (name, args) in enumerate(tool_steps):
            serialized_args = json.dumps(args, ensure_ascii=False)
            fragments = step.get("tool_argument_fragments") or [serialized_args]
            for index, fragment in enumerate(fragments):
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                **({"name": name, "id": None if step.get("omit_tool_ids") else f"call-{len(self.seen_message_counts)}" + (f"-{tool_index}" if len(tool_steps) > 1 else "")} if index == 0 else {}),
                                "args": fragment,
                                "index": None if step.get("omit_tool_indexes") else step.get("tool_indexes", range(len(tool_steps)))[tool_index],
                                "type": "tool_call_chunk",
                            }
                        ],
                    )
                )
                if index < len(fragments) - 1 and step.get("tool_argument_fragment_delay"):
                    await asyncio.sleep(float(step["tool_argument_fragment_delay"]))
        if step.get("hang_after_tool"):
            # Simulate a compatible gateway that sent complete JSON but never
            # sends the terminating stream frame. The agent must close it.
            await asyncio.sleep(60)

    def _generate(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - 只用流式
        raise NotImplementedError


def _run(
    model: ScriptedChatModel,
    session: HtmlEditSession,
    budget: int = 0,
    timeout: float | None = None,
    attached_templates: Sequence[dict[str, Any]] | None = None,
    tool_output_store: ToolOutputStore | None = None,
    selected_elements: Sequence[dict[str, Any]] | None = None,
    theme_application: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    async def go() -> list[dict[str, Any]]:
        return [
            event
            async for event in run_agent_loop(
                model,
                "端到端测试稿",
                session.html,
                "把标题改成《新标题》",
                session.document_map(),
                None,
                [],
                selected_elements,
                None,
                session,
                None,
                budget,
                attached_templates=attached_templates,
                tool_output_store=tool_output_store,
                theme_application=theme_application, tool_protocol="v1"
            )
        ]

    return asyncio.run(asyncio.wait_for(go(), timeout)) if timeout is not None else asyncio.run(go())


class AgentLoopEndToEndTests(unittest.TestCase):
    def test_missing_search_query_has_actionable_errors_and_recovers(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_html", {})},
                {"tool": ("search_html", {})},
                {"tool": ("search_html", {"query": "旧标题"})},
                {"text": "已定位标题。"},
            ], seen_message_counts=[], seen_messages=[],
        )
        with patch.object(session, "search", wraps=session.search) as search:
            events = _run(model, session)
        self.assertEqual(search.call_count, 1)
        results = [event["data"] for event in events if event["event"] == "tool_result"]
        self.assertEqual(len(results), 3)
        for index, result in enumerate(results[:2]):
            self.assertIn("缺少必填参数：query", result["result"])
            self.assertNotIn("ToolInvocationError", result["result"])
            self.assertEqual(result["activity"]["details"]["attempt"], index + 1)
            message = model.seen_messages[index + 1][-1]
            self.assertEqual(message.tool_call_id, result["id"])
            payload = json.loads(str(message.content))
            self.assertEqual(payload["missing_fields"], ["query"])
            self.assertFalse(payload["retry_same_arguments"])
            self.assertEqual(result["model_input"]["content"], str(message.content))
        self.assertIn("get_document_map", results[1]["activity"]["details"]["next_step"])
        self.assertEqual(results[2]["activity"]["kind"], "search")
        self.assertEqual(events[-1]["event"], "final")

    def test_provider_cumulative_search_arguments_use_the_complete_buffer(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_html", {"query": "旧标题"}), "tool_argument_fragments": ['{"query":', '{"query":"旧', '{"query":"旧标题"}']},
                {"text": "已定位标题。"},
            ], seen_message_counts=[], seen_messages=[],
        )
        with patch.object(session, "search", wraps=session.search) as search:
            events = _run(model, session)
        search.assert_called_once_with("旧标题", 8, 0)
        result = next(event["data"] for event in events if event["event"] == "tool_result")
        self.assertEqual(result["activity"]["kind"], "search")
        self.assertEqual(model.seen_messages[1][-2].tool_calls[0]["args"], {"query": "旧标题"})

    def test_search_accepts_encoded_wrappers_alias_and_optional_null(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_html", {"arguments": '{"keyword":"旧标题","limit":null}'})},
                {"text": "已定位标题。"},
            ], seen_message_counts=[], seen_messages=[],
        )
        with patch.object(session, "search", wraps=session.search) as search:
            events = _run(model, session)
        search.assert_called_once_with("旧标题", 8, 0)
        result = next(event["data"] for event in events if event["event"] == "tool_result")
        self.assertEqual(result["activity"]["kind"], "search")

    def test_truncated_write_arguments_are_not_executed_as_partial_json(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        arguments = {"revision": session.document_map()["revision"], "html": "<p>不得写入</p>"}
        model = ScriptedChatModel(
            script=[
                {"tool": ("replace_document", arguments), "tool_argument_fragments": [json.dumps(arguments)[:-1]]},
                {"text": "参数不完整，需要重新提交。"},
            ], seen_message_counts=[], seen_messages=[],
        )
        with patch.object(session, "replace_document", wraps=session.replace_document) as replace:
            events = _run(model, session)
        replace.assert_not_called()
        self.assertEqual(session.html, SOURCE_HTML)
        result = next(event["data"] for event in events if event["event"] == "tool_result")
        self.assertEqual(result["activity"]["details"]["code"], "invalid_tool_arguments")
        self.assertIn("完整", result["result"])
        self.assertEqual(events[-1]["event"], "final")

    def test_invalid_parallel_call_does_not_discard_the_valid_search(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tools": [("search_html", {}), ("search_html", {"keywords": "正文内容"})]},
                {"text": "已读取可定位的内容。"},
            ], seen_message_counts=[], seen_messages=[],
        )
        with patch.object(session, "search", wraps=session.search) as search:
            events = _run(model, session)
        search.assert_called_once_with("正文内容", 8, 0)
        results = {event["data"]["id"]: event["data"] for event in events if event["event"] == "tool_result"}
        self.assertEqual(set(results), {"call-1-0", "call-1-1"})
        self.assertEqual(results["call-1-0"]["activity"]["kind"], "error")
        self.assertEqual(results["call-1-1"]["activity"]["kind"], "search")
        messages = model.seen_messages[1][-2:]
        self.assertEqual([message.tool_call_id for message in messages], ["call-1-0", "call-1-1"])

    def test_parallel_calls_without_chunk_indexes_keep_arguments_separate(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tools": [("search_html", {"query": "旧标题"}), ("search_html", {"query": "正文内容"})], "omit_tool_indexes": True},
                {"text": "已分别定位。"},
            ], seen_message_counts=[], seen_messages=[],
        )
        with patch.object(session, "search", wraps=session.search) as search:
            events = _run(model, session)
        self.assertEqual(search.call_count, 2)
        self.assertCountEqual([call.args[0] for call in search.call_args_list], ["旧标题", "正文内容"])
        results = [event["data"] for event in events if event["event"] == "tool_result"]
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["activity"]["kind"] == "search" for result in results))

    def test_parallel_compliance_with_sparse_chunk_indexes_keeps_timeline_ids(self) -> None:
        for indexes in ([1, 2], [0, 3], [2, 7]):
            for omit_ids in (False, True):
                with self.subTest(indexes=indexes, omit_ids=omit_ids):
                    session = HtmlEditSession(SOURCE_HTML)
                    model = ScriptedChatModel(
                        script=[
                            {
                                "tools": [("read_blocks", {}), ("check_compliance", {})],
                                "tool_indexes": indexes,
                                "omit_tool_ids": omit_ids,
                            },
                            {"text": "核对完成。"},
                        ], seen_message_counts=[], seen_messages=[],
                    )
                    report = {"isValid": True, "violations": []}
                    with patch("app.services.chat_agent.run_compliance_check", return_value=SimpleNamespace(to_dict=lambda: report)) as checker:
                        events = _run(model, session)

                    checker.assert_called_once_with(SOURCE_HTML)
                    calls = [event["data"] for event in events if event["event"] == "tool_call"]
                    preparing = {call["name"]: call["id"] for call in calls if call.get("preparing")}
                    completed = [call for call in calls if not call.get("preparing")]
                    self.assertEqual({call["name"]: call["id"] for call in completed}, preparing)
                    self.assertTrue(all("replaces_id" not in call for call in completed))
                    results = [event["data"] for event in events if event["event"] == "tool_result"]
                    self.assertEqual(len(results), 2)
                    self.assertEqual({result["name"]: result["id"] for result in results}, preparing)

    def test_omitted_call_id_gets_a_matching_result_and_provider_history(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_html", {"query": "旧标题"}), "omit_tool_ids": True},
                {"text": "已定位。"},
            ], seen_message_counts=[], seen_messages=[],
        )
        events = _run(model, session)
        result = next(event["data"] for event in events if event["event"] == "tool_result")
        self.assertTrue(result["id"])
        self.assertEqual(result["activity"]["kind"], "search")
        assistant, tool_message = model.seen_messages[1][-2:]
        self.assertEqual(assistant.tool_calls[0]["id"], tool_message.tool_call_id)
        self.assertEqual(tool_message.tool_call_id, result["id"])

    def test_invalid_replace_document_is_preserved_and_returns_warning_to_model_and_ui(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "replace_document",
                        {
                            "revision": session.document_map()["revision"],
                            "html": "<section>\n  <strong>broken\n</section>",
                        },
                    )
                },
                {"text": "已根据明确的标签位置重新检查。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        warning = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "replace_document"
        )
        validation = warning["activity"]["html_validation"]
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["issues"][0]["code"], "missing_end_tag_before_close")
        self.assertIn("请根据上述 line、column、tag 和 message 对当前候选做局部修复", warning["result"])
        self.assertTrue(warning["activity"]["validation_warning"])
        self.assertEqual(session.html, "<section>\n  <strong>broken\n</section>")

        self.assertIsInstance(model.seen_messages[1][-1], ToolMessage)
        tool_payload = json.loads(str(model.seen_messages[1][-1].content))
        self.assertEqual(tool_payload["validation"]["issues"][0]["line"], 3)
        self.assertEqual(tool_payload["validation"]["issues"][0]["tag"], "section")
        self.assertTrue(tool_payload["ok"])
        self.assertEqual(tool_payload["warning"], validation)

    def test_theme_strict_rejection_reaches_model_and_allows_retry(self) -> None:
        source = '<section><p><span leaf="">原文</span></p></section>'
        valid_html = '<section><p><span leaf="">修复后的正文</span></p></section>'
        session = HtmlEditSession(source, candidate_validator=validate_gzh_theme_candidate)
        revision = session.document_map()["revision"]
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "replace_document",
                        {
                            "revision": revision,
                            "html": '<section style="float:left"><p>未包裹正文</p></section>',
                        },
                    )
                },
                {"tool": ("replace_document", {"revision": revision, "html": valid_html})},
                {"text": "已修复严格校验问题并完成主题排版。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(
            model,
            session,
            theme_application={"theme_name": "严格校验测试主题", "apply_mode": "full"},
        )

        failed = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result"
            and event["data"]["name"] == "replace_document"
            and event["data"]["activity"]["kind"] == "error"
        )
        strict = failed["activity"]["gzh_validation"]
        self.assertTrue(strict["hasError"])
        self.assertGreaterEqual(len(strict["errors"]), 2)
        self.assertIn("float", " ".join(strict["errors"]).lower())

        self.assertIsInstance(model.seen_messages[1][-1], ToolMessage)
        tool_payload = json.loads(str(model.seen_messages[1][-1].content))
        self.assertEqual(tool_payload["gzh_validation"]["errors"], strict["errors"])
        self.assertIn("当前 revision", tool_payload["next_step"])
        self.assertEqual(session.html, valid_html)
        self.assertTrue(session.edited)
        self.assertEqual(events[-1]["event"], "final")

    def test_session_history_result_reaches_model_and_timeline_with_call_id(self) -> None:
        """A tool that only returns ToolMessage must still settle the live UI."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_session_history", {"query": "标题"})},
                {"text": "已检索到会话中的相关记录。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        store = ToolOutputStore(document_id=1, session_id=1, run_id="session-history-test")

        with (
            patch("app.services.chat_agent.SessionLocal", side_effect=lambda: nullcontext(object())),
            patch(
                "app.services.chat_agent.SessionHistoryReader.search",
                return_value={"ok": True, "results": [], "next_cursor": None},
            ),
        ):
            events = _run(model, session, tool_output_store=store)

        result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "search_session_history"
        )
        self.assertEqual(result["id"], "call-1")
        self.assertEqual(result["result"], "已检索会话历史")
        self.assertEqual(result["activity"]["kind"], "search")
        self.assertIsInstance(model.seen_messages[1][-1], ToolMessage)
        self.assertEqual(model.seen_messages[1][-1].tool_call_id, "call-1")
        self.assertIn('"ok":true', str(model.seen_messages[1][-1].content))
        self.assertEqual(result["model_input"]["state"], "available")
        self.assertEqual(result["model_input"]["content"], str(model.seen_messages[1][-1].content))

    def test_attached_template_reader_accepts_json_array_tool_argument(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("read_attached_templates", {"template_ids": "[1, 2]"})},
                {"text": "已读取并准备套用组件。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(
            model,
            session,
            attached_templates=[
                {"id": 1, "name": "组件一", "html": "<section><p>组件一</p></section>"},
                {"id": 2, "name": "组件二", "html": "<section><p>组件二</p></section>"},
            ],
        )

        result = next(
            event["data"]["result"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "read_attached_templates"
        )
        self.assertIn("已读取 2 个附加模板", result)
        self.assertEqual(events[-1]["event"], "final")

    def test_theme_component_reader_accepts_json_array_tool_argument(self) -> None:
        session = HtmlEditSession(
            '<section><h1><span leaf="">标题</span></h1><p><span leaf="">正文内容</span></p></section>'
        )
        model = ScriptedChatModel(
            script=[
                {"tool": ("read_gzh_theme_components", {"component_ids": '["1", "2"]'})},
                {"text": "已读取主题组件。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        theme_application = {
            "theme_name": "数组兼容主题",
            "article_type": "教程/操作指南",
            "recipe_id": "recipe-01",
            "selected_component_ids": ["1", "2", "6d"],
            "components": [
                {"id": "1", "name": "标题", "html": "<h1>标题</h1>"},
                {"id": "2", "name": "导语", "html": "<p>导语</p>"},
                {"id": "6d", "name": "引用", "html": "<blockquote>引用</blockquote>"},
            ],
        }

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "主题组件参数兼容测试稿",
                    session.html,
                    "读取主题组件",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    theme_application=theme_application, tool_protocol="v1"
                )
            ]

        events = asyncio.run(go())

        result = next(
            event["data"]["result"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "read_gzh_theme_components"
        )
        self.assertIn("已读取 2 个已确认主题组件", result)
        self.assertEqual(events[-1]["event"], "final")

    def test_validation_tools_are_exposed_only_for_their_applicable_context(self) -> None:
        ordinary_model = ScriptedChatModel(
            script=[{"text": "无需修改。"}],
            seen_message_counts=[],
            seen_messages=[],
            bound_tool_names=[],
        )
        _run(ordinary_model, HtmlEditSession(SOURCE_HTML))

        self.assertIn("check_compliance", ordinary_model.bound_tool_names)
        self.assertIn("read_wechat_compliance_spec", ordinary_model.bound_tool_names)
        self.assertIn("search_article_images", ordinary_model.bound_tool_names)
        self.assertIn("view_article_images", ordinary_model.bound_tool_names)
        self.assertIn("import_searched_image", ordinary_model.bound_tool_names)
        self.assertIn("apply_searched_cover", ordinary_model.bound_tool_names)
        self.assertIn("transform_document_image", ordinary_model.bound_tool_names)
        self.assertNotIn("apply_searched_image", ordinary_model.bound_tool_names)
        self.assertNotIn("validate_gzh_html", ordinary_model.bound_tool_names)

        theme_model = ScriptedChatModel(
            script=[{"text": "主题任务已准备。"}],
            seen_message_counts=[],
            seen_messages=[],
            bound_tool_names=[],
        )
        theme_application = {
            "theme_name": "测试主题",
            "apply_mode": "full",
            "article_type": "通用",
            "selected_component_ids": ["heading"],
        }

        async def go() -> None:
            async for _ in run_agent_loop(
                theme_model,
                "主题工具可见性测试稿",
                SOURCE_HTML,
                "应用主题",
                HtmlEditSession(SOURCE_HTML).document_map(),
                None,
                [],
                theme_application=theme_application, tool_protocol="v1"
            ):
                pass

        asyncio.run(go())

        self.assertIn("check_compliance", theme_model.bound_tool_names)
        self.assertIn("validate_gzh_html", theme_model.bound_tool_names)

    def test_read_blocks_tool_accepts_oversized_block_continuation_cursor(self) -> None:
        source = "<section><p>" + ("很长的正文" * 350) + "</p></section>"
        session = HtmlEditSession(source, tool_result_max_tokens=512)
        block_id = next(block.block_id for block in session.workspace().blocks if block.tag == "section")
        first_page = session.read_blocks([block_id])
        self.assertIsInstance(first_page["next_cursor"], str)
        model = ScriptedChatModel(
            script=[
                {"tool": ("read_blocks", {"block_ids": [block_id]})},
                {"tool": ("read_blocks", {"block_ids": [block_id], "cursor": first_page["next_cursor"]})},
                {"text": "已继续读取源码。"},
            ],
            seen_message_counts=[], seen_messages=[],
        )

        events = _run(model, session)

        results = [
            event["data"] for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "read_blocks"
        ]
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["activity"]["kind"] == "read" for result in results))
        first_content = next(
            message.content for message in model.seen_messages[1]
            if isinstance(message, ToolMessage) and message.name == "read_blocks"
        )
        second_contents = [
            message.content for message in model.seen_messages[2]
            if isinstance(message, ToolMessage) and message.name == "read_blocks"
        ]
        self.assertIn("html_fragment", str(first_content))
        self.assertEqual(len(second_contents), 2)
        self.assertEqual(json.loads(str(second_contents[1]))["cursor"], first_page["next_cursor"])

    def test_multimodal_view_tool_injects_ephemeral_image_message(self) -> None:
        image_bytes = b"not-a-real-image-but-validated-by-the-test"
        source = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        session = HtmlEditSession(f'<section><img src="{source}" alt="活动图片"></section>')
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "view_article_images",
                        {"references": [{"kind": "article", "image_slot": 1, "revision": session.workspace().revision}]},
                    )
                },
                {"text": "已查看文章图片。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="vision-view-test")

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "多模态测试稿",
                    session.html,
                    "请查看文章内图片",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    tool_output_store=store,
                    actor_user_id=7,
                    model_is_multimodal=True,
                    provider_type="openai_compatible", tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
            patch("app.services.local_uploads.inspect_image", return_value=SimpleNamespace(content_type="image/png", width=640, height=360)),
        ):
            events = asyncio.run(go())
        try:
            self.assertEqual(events[-1]["event"], "final")
            self.assertTrue(any(isinstance(message, HumanMessage) for message in model.seen_messages[1]))
            visual_message = next(
                message
                for message in model.seen_messages[1]
                if isinstance(message, HumanMessage) and getattr(message, "additional_kwargs", {}).get("ephemeral_tool_images")
            )
            self.assertTrue(any(block.get("type") == "image_url" for block in visual_message.content))
            result = next(
                event["data"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "view_article_images"
            )
            self.assertEqual(result["activity"]["kind"], "image_view")
            self.assertTrue(result["activity"]["details"]["include_image_requested"])
            self.assertTrue(result["activity"]["details"]["image_content_included"])
            self.assertEqual(result["activity"]["details"]["items"][0]["width"], 640)
            self.assertEqual(result["activity"]["details"]["items"][0]["height"], 360)
            self.assertNotIn("preview_url", result["activity"]["details"]["items"][0])
            text_result = next(
                message
                for message in model.seen_messages[1]
                if isinstance(message, ToolMessage) and message.name == "view_article_images"
            )
            self.assertEqual(result["model_input"]["content"], str(text_result.content))
            self.assertNotIn(base64.b64encode(image_bytes).decode("ascii"), result["model_input"]["content"])
            completed_call = next(
                event["data"] for event in events
                if event["event"] == "tool_call" and event["data"]["name"] == "view_article_images"
                and not event["data"].get("preparing")
            )
            self.assertTrue(completed_call["arguments"]["include_image"])
            persisted_context = [
                event["data"].get("context_events", [])
                for event in events
                if isinstance(event.get("data"), dict) and event["event"] in {"final", "error"}
            ]
            self.assertNotIn(base64.b64encode(image_bytes).decode("ascii"), json.dumps(persisted_context, ensure_ascii=False))
        finally:
            engine.dispose()

    def test_chat_image_view_reads_active_session_only(self) -> None:
        image_bytes = b"chat-image-pixels"
        session = HtmlEditSession(SOURCE_HTML)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            current_session = ChatSession(document_id=1, title="current")
            other_session = ChatSession(document_id=1, title="other")
            db.add_all([current_session, other_session])
            db.flush()
            old = ChatMessage(document_id=1, session_id=current_session.id, role=MessageRole.USER, content="old")
            active = ChatMessage(document_id=1, session_id=current_session.id, role=MessageRole.USER, content="active")
            superseded = ChatMessage(document_id=1, session_id=current_session.id, role=MessageRole.USER, content="superseded", is_superseded=True)
            foreign = ChatMessage(document_id=1, session_id=other_session.id, role=MessageRole.USER, content="foreign")
            db.add_all([old, active, superseded, foreign])
            db.flush()
            current_session.context_start_message_id = old.id
            for key, message in (("old", old), ("active", active), ("superseded", superseded), ("foreign", foreign)):
                db.add(ChatImageAttachment(
                    id=f"chat-{key}", document_id=1, uploader_id=7,
                    message_id=message.id, filename=f"{key}.png", content_type="image/png",
                    size=len(image_bytes), storage_mode="local", object_key=f"{key}.png",
                ))
            db.commit()
            current_session_id = current_session.id

        model = ScriptedChatModel(
            script=[
                {"tool": ("view_article_images", {"references": [{"kind": "chat", "attachment_id": f"chat-{key}"}]})}
                for key in ("active", "old", "superseded", "foreign")
            ] + [{"text": "已查看当前会话图片。"}],
            seen_message_counts=[], seen_messages=[],
        )
        store = ToolOutputStore(document_id=1, session_id=current_session_id, run_id="chat-image-view-test")

        async def go() -> list[dict[str, Any]]:
            return [
                event async for event in run_agent_loop(
                    model, "会话图片测试稿", session.html, "查看附图", session.document_map(),
                    None, [], session=session, tool_output_store=store,
                    actor_user_id=7, model_is_multimodal=True,
                    provider_type="openai_compatible", tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
            patch("app.services.chat_agent.read_attachment_bytes", return_value=image_bytes) as read_image,
            patch("app.services.document_image_transform.read_document_image_dimensions", return_value=("image/png", 640, 360)),
        ):
            events = asyncio.run(go())
        try:
            results = [
                event["data"] for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "view_article_images"
            ]
            self.assertEqual(len(results), 4)
            self.assertEqual(results[0]["activity"]["details"]["items"][0]["kind"], "chat")
            self.assertEqual(results[0]["activity"]["details"]["items"][0]["width"], 640)
            self.assertTrue(all(result["activity"]["kind"] == "error" for result in results[1:]))
            self.assertEqual(read_image.call_count, 1)
            visual_messages = [
                message for message in model.seen_messages[1]
                if isinstance(message, HumanMessage) and getattr(message, "additional_kwargs", {}).get("ephemeral_tool_images")
            ]
            self.assertEqual(len(visual_messages), 1)
            self.assertIn(base64.b64encode(image_bytes).decode("ascii"), json.dumps(visual_messages[0].content))
            self.assertNotIn(base64.b64encode(image_bytes).decode("ascii"), json.dumps(results))
        finally:
            engine.dispose()

    def test_text_only_image_view_returns_actual_dimensions(self) -> None:
        image_bytes = b"not-a-real-image-but-validated-by-the-test"
        source = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        session = HtmlEditSession(f'<section><img src="{source}" alt="活动图片"></section>')
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "view_article_images",
                        {"references": [{"kind": "article", "image_slot": 1, "revision": session.workspace().revision}]},
                    )
                },
                {"text": "已读取图片尺寸。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="dimension-text-only-test")

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "尺寸测试稿",
                    session.html,
                    "读取文章内图片尺寸",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    tool_output_store=store,
                    actor_user_id=7,
                    model_is_multimodal=False,
                    provider_type="openai_compatible", tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
            patch("app.services.local_uploads.inspect_image", return_value=SimpleNamespace(content_type="image/png", width=1200, height=628)),
        ):
            events = asyncio.run(go())
        try:
            result = next(
                event["data"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "view_article_images"
            )
            details = result["activity"]["details"]
            self.assertFalse(details["vision_supported"])
            self.assertTrue(details["include_image_requested"])
            self.assertFalse(details["image_content_included"])
            self.assertIn("当前模型不支持图片输入", details["notice"])
            self.assertIn("当前模型不支持看图", result["result"])
            self.assertEqual(details["viewed_count"], 0)
            self.assertEqual(details["items"][0]["width"], 1200)
            self.assertEqual(details["items"][0]["height"], 628)
        finally:
            engine.dispose()

    def test_multimodal_image_view_can_return_dimensions_without_injecting_pixels(self) -> None:
        image_bytes = b"dimensions-only-image"
        source = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        session = HtmlEditSession(f'<section><img src="{source}" alt="活动图片"></section>')
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "view_article_images",
                        {
                            "references": [{"kind": "article", "image_slot": 1, "revision": session.workspace().revision}],
                            "include_image": False,
                        },
                    )
                },
                {"text": "已读取图片尺寸。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="dimension-only-multimodal-test")

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "尺寸测试稿",
                    session.html,
                    "读取文章内图片尺寸",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    tool_output_store=store,
                    actor_user_id=7,
                    model_is_multimodal=True,
                    provider_type="openai_compatible", tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
            patch("app.services.local_uploads.inspect_image", return_value=SimpleNamespace(content_type="image/png", width=1200, height=628)),
        ):
            events = asyncio.run(go())
        try:
            self.assertEqual(events[-1]["event"], "final")
            self.assertFalse(
                any(
                    isinstance(message, HumanMessage) and getattr(message, "additional_kwargs", {}).get("ephemeral_tool_images")
                    for message in model.seen_messages[1]
                )
            )
            result = next(
                event["data"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "view_article_images"
            )
            details = result["activity"]["details"]
            self.assertTrue(details["vision_supported"])
            self.assertFalse(details["include_image_requested"])
            self.assertFalse(details["image_content_included"])
            self.assertIn("本次调用选择仅读取尺寸", details["notice"])
            self.assertIn("仅请求尺寸", result["result"])
            self.assertEqual(details["viewed_count"], 0)
            self.assertEqual((details["items"][0]["width"], details["items"][0]["height"]), (1200, 628))
            self.assertNotIn("preview_url", details["items"][0])
            completed_call = next(
                event["data"] for event in events
                if event["event"] == "tool_call" and event["data"]["name"] == "view_article_images"
                and not event["data"].get("preparing")
            )
            self.assertEqual(completed_call["arguments"], {"include_image": False})
        finally:
            engine.dispose()

    def test_stale_article_image_references_are_reconciled_after_unrelated_edit(self) -> None:
        inserted_bytes = b"inserted-image-bytes"
        first_bytes = b"first-image-bytes"
        second_bytes = b"second-image-bytes"
        inserted_source = f"data:image/png;base64,{base64.b64encode(inserted_bytes).decode('ascii')}"
        first_source = f"data:image/png;base64,{base64.b64encode(first_bytes).decode('ascii')}"
        second_source = f"data:image/png;base64,{base64.b64encode(second_bytes).decode('ascii')}"
        original_html = (
            f'<section><p>原始正文</p><img src="{first_source}" alt="第一张图">'
            f'<p>补充说明</p><img src="{second_source}" alt="第二张图"></section>'
        )
        updated_html = original_html.replace(
            f'<img src="{first_source}"',
            f'<img src="{inserted_source}" alt="插入图片"><img src="{first_source}"',
        ).replace("原始正文", "正文已调整")
        session = HtmlEditSession(original_html)
        initial_revision = session.workspace().revision
        initial_images = session.workspace().image_inventory()["images"]
        model = ScriptedChatModel(
            script=[
                {"tool": ("inspect_current_images", {})},
                {"tool": ("replace_document", {"revision": initial_revision, "html": updated_html})},
                {
                    "tool": (
                        "view_article_images",
                        {
                            "references": [
                                {
                                    "kind": "article",
                                    "image_slot": 1,
                                    "revision": initial_revision,
                                    "source_fingerprint": initial_images[0]["source_fingerprint"],
                                },
                                {"kind": "article", "image_slot": 2, "revision": "older-unseen-revision"},
                            ]
                        },
                    )
                },
                {"text": "已查看文章图片。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="stale-vision-reference-test")

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "多模态测试稿",
                    session.html,
                    "请查看文章内图片",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    tool_output_store=store,
                    actor_user_id=7,
                    model_is_multimodal=True,
                    provider_type="openai_compatible", tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
            patch("app.services.local_uploads.inspect_image", return_value=SimpleNamespace(content_type="image/png", width=640, height=360)),
        ):
            events = asyncio.run(go())
        try:
            self.assertEqual(events[-1]["event"], "final")
            result = next(
                event["data"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "view_article_images"
            )
            self.assertEqual(result["activity"]["kind"], "image_view")
            self.assertEqual(result["activity"]["details"]["viewed_count"], 2)
            self.assertEqual(
                [item["label"].split(" · ", 1)[0] for item in result["activity"]["details"]["items"]],
                ["文章图片 2", "文章图片 3"],
            )
            visual_message = next(
                message
                for message in model.seen_messages[3]
                if isinstance(message, HumanMessage)
                and getattr(message, "additional_kwargs", {}).get("ephemeral_tool_images")
            )
            self.assertEqual(
                [block["type"] for block in visual_message.content if block["type"] == "image_url"],
                ["image_url", "image_url"],
            )
        finally:
            engine.dispose()

    def test_unseen_stale_article_image_reference_is_rejected_without_image_injection(self) -> None:
        image_bytes = b"unseen-stale-image"
        source = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        session = HtmlEditSession(f'<section><img src="{source}" alt="未盘点图片"></section>')
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "view_article_images",
                        {"references": [{"kind": "article", "image_slot": 1, "revision": "stale-revision"}]},
                    )
                },
                {"text": "无法安全读取该图片。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="unseen-stale-vision-reference-test")

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "多模态测试稿",
                    session.html,
                    "请查看文章内图片",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    tool_output_store=store,
                    actor_user_id=7,
                    model_is_multimodal=True,
                    provider_type="openai_compatible", tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
        ):
            events = asyncio.run(go())
        try:
            result = next(
                event["data"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "view_article_images"
            )
            self.assertEqual(result["activity"]["kind"], "error")
            self.assertIn("缺少可恢复指纹", result["result"])
            self.assertFalse(
                any(
                    isinstance(message, HumanMessage)
                    and getattr(message, "additional_kwargs", {}).get("ephemeral_tool_images")
                    for message in model.seen_messages[1]
                )
            )
        finally:
            engine.dispose()

    def test_image_search_exposes_compact_candidate_references_to_model(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        candidate = ImageSearchCandidate(
            id="park-candidate",
            image_url="https://images.example.test/park.jpg",
            preview_url="https://images.example.test/park-small.jpg",
            source_page_url="https://example.test/park",
            title="城市公园",
            engine="bing images",
            width=1600,
            height=900,
            image_format="jpeg",
        )
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_article_images", {"query": "城市公园", "limit": 1})},
                {"text": "已获得候选。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="compact-search-reference-test")

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "搜图短引用测试稿",
                    session.html,
                    "为文章找一张城市公园配图",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    tool_output_store=store,
                    actor_user_id=7, tool_protocol="v1"
                )
            ]

        try:
            with (
                patch("app.services.chat_agent.SessionLocal", factory),
                patch("app.services.tool_output_store.SessionLocal", factory),
                patch("app.db.session.SessionLocal", factory),
                patch(
                    "app.services.image_search.search_images_with_cursor",
                    new=AsyncMock(return_value=([candidate], None)),
                ),
            ):
                events = asyncio.run(go())
                model_result = next(
                    message
                    for message in model.seen_messages[1]
                    if isinstance(message, ToolMessage) and message.name == "search_article_images"
                )
                payload = json.loads(str(model_result.content))
                compact_item = payload["items"][0]
                decoded = decode_candidate_reference(
                    compact_item["candidate_ref"], user_id=7, document_id=1
                )

            self.assertEqual(events[-1]["event"], "final")
            self.assertNotIn("token", compact_item)
            self.assertNotIn("preview_url", compact_item)
            self.assertLess(len(compact_item["candidate_ref"]), 128)
            self.assertEqual(decoded.id, candidate.id)
            activity = next(
                event["data"]["activity"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "search_article_images"
            )
            self.assertTrue(activity["details"]["items"][0]["token"])
        finally:
            engine.dispose()

    def _patch_script(self, session: HtmlEditSession) -> list[dict[str, Any]]:
        blocks = session.search("旧标题")["results"]
        heading = next(item for item in blocks if item["tag"] == "h1")
        read = session.read_blocks([heading["block_id"]])
        block = read["blocks"][0]
        return [
            {"text": "先定位标题。", "tool": ("search_html", {"query": "旧标题"})},
            {
                "tool": (
                    "apply_html_patch",
                    {
                        "revision": read["revision"],
                        "operations": [
                            {
                                "block_id": block["block_id"],
                                "expected_hash": block["expected_hash"],
                                "mode": "replace_inner",
                                "html": "新标题",
                            }
                        ],
                    },
                )
            },
            {"tool": ("check_compliance", {})},
            {"text": "已将标题改为《新标题》。"},
        ]

    def test_full_loop_edits_the_document_and_finishes(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=self._patch_script(session), seen_message_counts=[], seen_messages=[]
        )

        report = {"isValid": True, "violations": [], "warnMsgs": []}
        with patch("app.services.chat_agent.run_compliance_check", return_value=SimpleNamespace(to_dict=lambda: report)) as checker:
            events = _run(model, session)
        checker.assert_called_once_with(session.html)

        kinds = [event["event"] for event in events]
        self.assertEqual(kinds[-1], "final")
        self.assertNotIn("error", kinds)
        self.assertIn("tool_call", kinds)
        self.assertIn("tool_result", kinds)
        completed_tools = [
            event["data"]
            for event in events
            if event["event"] == "tool_result"
        ]
        tool_contexts = [
            event["data"]
            for event in events
            if event["event"] == "context_stats" and event["data"].get("state") == "tool_result_context"
        ]
        self.assertEqual(len(tool_contexts), len(completed_tools))
        self.assertEqual(
            [context["tool_call_id"] for context in tool_contexts],
            [tool["id"] for tool in completed_tools],
        )
        model_compliance_result = next(
            tool for tool in completed_tools if tool["name"] == "check_compliance"
        )
        self.assertIsInstance(model_compliance_result["activity"].get("compliance"), dict)
        self.assertTrue(all(context["used_tokens"] > 0 for context in tool_contexts))
        runtime_stats = [
            event["data"]
            for event in events
            if event["event"] == "context_stats" and event["data"].get("state") == "streaming"
        ]
        request_stats = [
            event["data"]
            for event in events
            if event["event"] == "context_stats" and event["data"].get("state") == "request_context"
        ]
        self.assertTrue(request_stats)
        self.assertGreater(request_stats[0]["breakdown"]["runtime_system"], 0)
        self.assertEqual(sum(request_stats[0]["breakdown"].values()), request_stats[0]["used_tokens"])
        self.assertTrue(runtime_stats, "流式输出期间必须持续发布上下文遥测")
        self.assertGreater(runtime_stats[0]["runtime_projected_tokens"], 0)
        self.assertEqual(sum(runtime_stats[0]["breakdown"].values()), runtime_stats[0]["used_tokens"])

        final = events[-1]["data"]
        self.assertTrue(final["html_changed"])
        self.assertIn("新标题", final["html"])
        self.assertNotIn("旧标题", final["html"])
        self.assertEqual(final["content"], "已将标题改为《新标题》。")
        self.assertEqual(final["compliance"], report)
        # 会话对象与 final 事件必须一致，取消时的部分持久化依赖这一点。
        self.assertEqual(session.html, final["html"])

    def test_continuous_local_patches_reuse_an_untouched_block_without_reloading_map(self) -> None:
        source = "<section><p>first</p><p>second</p></section>"
        session = HtmlEditSession(source)
        first = next(item for item in session.search("first")["results"] if item["tag"] == "p")
        second = next(item for item in session.search("second")["results"] if item["tag"] == "p")
        read = session.read_blocks([first["block_id"], second["block_id"]])
        hashes = {block["block_id"]: block["expected_hash"] for block in read["blocks"]}
        after_first = source.replace("first", "FIRST-UPDATED")
        after_first_revision = HtmlWorkspace.revision_for(after_first)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_html", {"query": "first second"})},
                {"tool": ("read_blocks", {"block_ids": [first["block_id"], second["block_id"]]})},
                {
                    "tool": (
                        "apply_html_patch",
                        {
                            "revision": read["revision"],
                            "operations": [
                                {
                                    "block_id": first["block_id"],
                                    "expected_hash": hashes[first["block_id"]],
                                    "mode": "replace_inner",
                                    "html": "FIRST-UPDATED",
                                }
                            ],
                        },
                    )
                },
                {
                    "tool": (
                        "apply_html_patch",
                        {
                            "revision": after_first_revision,
                            "operations": [
                                {
                                    "block_id": second["block_id"],
                                    "expected_hash": hashes[second["block_id"]],
                                    "mode": "replace_inner",
                                    "html": "SECOND-UPDATED",
                                }
                            ],
                        },
                    )
                },
                {"tool": ("check_compliance", {})},
                {"text": "两处独立段落已连续更新。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)
        tool_names = [
            event["data"]["name"]
            for event in events
            if event["event"] == "tool_call" and not event["data"].get("preparing")
        ]
        first_edit_activity = next(
            event["data"]["activity"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "apply_html_patch"
        )

        self.assertEqual(
            tool_names,
            [
                "search_html",
                "read_blocks",
                "apply_html_patch",
                "apply_html_patch",
                "check_compliance",
            ],
        )
        self.assertNotIn("get_document_map", tool_names)
        self.assertGreater(first_edit_activity["continuity"]["preserved_block_count"], 0)
        self.assertIn("FIRST-UPDATED", session.html)
        self.assertIn("SECOND-UPDATED", session.html)
        self.assertEqual(events[-1]["event"], "final")

    def test_selected_anchor_is_relocated_before_the_next_model_turn(self) -> None:
        source = '<section><p><img src="https://cdn.example/target.png"></p><p>其他内容</p></section>'
        session = HtmlEditSession(source)
        section = next(block for block in session.workspace().blocks if block.tag == "section")
        next_html = '<p>其他内容</p><p><img src="https://cdn.example/target.png"></p>'
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "apply_html_patch",
                        {
                            "revision": session.workspace().revision,
                            "operations": [
                                {
                                    "block_id": section.block_id,
                                    "expected_hash": section.expected_hash,
                                    "mode": "replace_inner",
                                    "html": next_html,
                                }
                            ],
                        },
                    )
                },
                {"text": "已移动选中图片。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )
        anchor = {
            "selector": "section:nth-of-type(1) > p:nth-of-type(1) > img:nth-of-type(1)",
            "tag_name": "img",
            "html": '<img src="https://cdn.example/target.png">',
            "text": "",
            "locator": {
                "path": "section:nth-of-type(1) > p:nth-of-type(1) > img:nth-of-type(1)",
                "parent_path": "section:nth-of-type(1) > p:nth-of-type(1)",
                "sibling_index": 1,
                "fingerprint": {
                    "tag_name": "img",
                    "stable_attributes": {"src": "https://cdn.example/target.png"},
                    "text": "",
                },
            },
        }

        events = _run(model, session, selected_elements=[anchor])

        self.assertEqual(events[-1]["event"], "final")
        self.assertGreaterEqual(len(model.seen_messages), 2)
        first_system = model.seen_messages[0][0]
        second_system = model.seen_messages[1][0]
        first_user = model.seen_messages[0][-1]
        self.assertIsInstance(first_system, SystemMessage)
        self.assertIsInstance(second_system, SystemMessage)
        self.assertIn("结构化选中锚点", str(first_user.content))
        self.assertIn('"status":"exact"', str(first_user.content))
        self.assertIn("section:nth-of-type(1) > p:nth-of-type(1) > img:nth-of-type(1)", str(first_user.content))
        self.assertIn("status=exact", str(first_system.content))
        self.assertIn("image_slot=1", str(first_system.content))
        self.assertIn("status=relocated", str(second_system.content))
        self.assertIn("image_slot=1", str(second_system.content))
        self.assertIn(
            "path=section:nth-of-type(1) > p:nth-of-type(2) > img:nth-of-type(1)",
            str(second_system.content),
        )

    def test_image_inventory_explicitly_marks_the_selected_image_anchor(self) -> None:
        source = (
            "<article><p>活动开场</p><p><img src='https://cdn.example/opening.png' alt='开场图'></p>"
            "<p>活动主题</p><p><img src='https://cdn.example/theme.png' alt='主题图'></p></article>"
        )
        session = HtmlEditSession(source)
        selected_path = "article:nth-of-type(1) > p:nth-of-type(2) > img:nth-of-type(1)"
        model = ScriptedChatModel(
            script=[{"tool": ("inspect_current_images", {})}, {"text": "已确认用户选中的图片。"}],
            seen_message_counts=[],
            seen_messages=[],
        )
        anchor = {
            "selector": selected_path,
            "tag_name": "img",
            "html": "<img src='https://cdn.example/opening.png' alt='开场图'>",
            "text": "",
            "locator": {
                "path": selected_path,
                "parent_path": "article:nth-of-type(1) > p:nth-of-type(2)",
                "sibling_index": 1,
                "fingerprint": {
                    "tag_name": "img",
                    "stable_attributes": {"src": "https://cdn.example/opening.png"},
                    "text": "",
                },
            },
        }

        events = _run(model, session, selected_elements=[anchor])

        self.assertEqual(events[-1]["event"], "final")
        inventory_result = next(
            message for message in model.seen_messages[1] if getattr(message, "name", "") == "inspect_current_images"
        )
        payload = json.loads(str(inventory_result.content))
        self.assertEqual(payload["selection"], {
            "received": True,
            "selected_element_count": 1,
            "selected_image_count": 1,
            "selected_images": [{
                "selected_element_index": 1,
                "status": "exact",
                "path": selected_path,
                "block_id": payload["images"][0]["block_id"],
                "image_slot": 1,
                "location_label": payload["images"][0]["location_label"],
                "reason": "",
            }],
            "non_image_element_indexes": [],
            "unresolved_image_element_indexes": [],
        })
        self.assertTrue(payload["images"][0]["selected_anchor"])
        self.assertEqual(payload["images"][0]["selected_element_indexes"], [1])
        self.assertFalse(payload["images"][1]["selected_anchor"])
        activity = next(
            event["data"]["activity"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "inspect_current_images"
        )
        self.assertIn("用户选中 @元素1", activity["targets"][0]["text"])

    def test_bound_layout_template_is_readable_by_tools_without_entering_system_prompt(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        reference_html = (
            '<section style="position:relative;background:url(/api/documents/local-images/tape.png)">'
            '<p style="margin:0">参考模板正文</p></section>'
        )
        reference_workspace = HtmlWorkspace(reference_html)
        reference_block = reference_workspace.map_payload()["blocks"][0]
        model = ScriptedChatModel(
            script=[
                {"tool": ("get_layout_reference_map", {})},
                {"tool": ("read_layout_reference_blocks", {"block_ids": [reference_block["block_id"]]})},
                {"tool": ("check_compliance", {})},
                {"text": "已按参考模板核对结构。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "端到端测试稿",
                    session.html,
                    "继续按参考模板调整",
                    session.document_map(),
                    None,
                    [],
                    layout_reference={
                        "title": "参考模板",
                        "site_name": "example.com",
                        "extracted_from": "article 正文",
                        "html": reference_html,
                        "block_count": 2,
                        "image_slots": 1,
                        "image_assets": 1,
                    },
                    session=session, tool_protocol="v1"
                )
            ]

        events = asyncio.run(go())
        tool_names = [
            event["data"]["name"]
            for event in events
            if event["event"] == "tool_call" and not event["data"].get("preparing")
        ]
        system_prompt = str(model.seen_messages[0][0].content)

        self.assertEqual(tool_names[:2], ["get_layout_reference_map", "read_layout_reference_blocks"])
        self.assertIn("get_layout_reference_map", system_prompt)
        self.assertNotIn("参考模板正文", system_prompt)
        self.assertNotIn("https://mp.weixin.qq.com/s/", system_prompt)

    def test_terminal_event_exports_provider_visible_cross_turn_ledger(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=self._patch_script(session), seen_message_counts=[], seen_messages=[]
        )

        events = _run(model, session)
        ledger = events[-1]["data"].get("context_events", [])

        self.assertTrue(ledger)
        tool_calls = {
            call["id"]
            for event in ledger
            if event["kind"] == "assistant"
            for call in event["payload"].get("tool_calls", [])
        }
        tool_results = {
            event["payload"]["tool_call_id"]
            for event in ledger
            if event["kind"] == "tool"
        }
        self.assertTrue(tool_calls)
        self.assertEqual(tool_calls, tool_results)
        self.assertTrue(any(event["kind"] == "assistant" and event["payload"].get("content") for event in ledger))

    def test_image_replacement_uses_current_semantic_locator_without_searching_history_or_html(self) -> None:
        source = (
            "<article>"
            "<p>校徽</p><p><img src='https://cdn.example/logo.png'></p>"
            "<p>主标题后的宣传横幅</p><p><img src='https://cdn.example/banner-old.png'></p>"
            "<p>一、活动主题</p><p><img src='https://cdn.example/theme-old.png'></p>"
            "<p>二、活动对象</p><p><img src='https://cdn.example/audience.png'></p>"
            "<p>七、报名方式</p><p><img src='https://cdn.example/signup-old.png'></p>"
            "<p>附件 1：</p><p><img src='https://cdn.example/form.png'></p>"
            "<p>附件 2：</p><p><img src='https://cdn.example/qrcode.png'></p>"
            "</article>"
        )
        session = HtmlEditSession(source)
        workspace = session.workspace()
        target_queries = ["宣传横幅", "活动主题", "报名方式"]
        targets = [workspace.image_inventory(query=query, limit=8)["images"][0] for query in target_queries]
        read = session.read_blocks([item["block_id"] for item in targets])
        replacements = [
            {
                "block_id": block["block_id"],
                "expected_hash": block["expected_hash"],
                "mode": "replace_outer",
                "html": f"<img src='https://cdn.example/new-{index}.png' alt='更新配图 {index}'>",
            }
            for index, block in enumerate(read["blocks"], start=1)
        ]
        model = ScriptedChatModel(
            script=[
                {"tool": ("inspect_current_images", {"query": "活动主题", "limit": 8})},
                {"tool": ("read_blocks", {"block_ids": [item["block_id"] for item in targets]})},
                {"tool": ("apply_html_patch", {"revision": read["revision"], "operations": replacements})},
                {"tool": ("check_compliance", {})},
                {"text": "三处配图已根据当前文章位置更新。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)
        tool_names = [
            event["data"]["name"]
            for event in events
            if event["event"] == "tool_call" and not event["data"].get("preparing")
        ]
        activity = next(
            event["data"]["activity"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "inspect_current_images"
        )

        self.assertEqual(
            tool_names,
            ["inspect_current_images", "read_blocks", "apply_html_patch", "check_compliance"],
        )
        inspect_call = next(
            event["data"]
            for event in events
            if event["event"] == "tool_call"
            and not event["data"].get("preparing")
            and event["data"]["name"] == "inspect_current_images"
        )
        self.assertEqual(
            inspect_call["arguments"],
            {"query": "活动主题", "limit": 8, "cursor": 0},
        )
        self.assertEqual(len(activity["targets"]), 1)
        self.assertIn("前文：一、活动主题", activity["targets"][0]["text"])
        self.assertNotIn("search_html", tool_names)
        self.assertNotIn("search_history_version", tool_names)
        self.assertIn("form.png", session.html)
        self.assertIn("new-3.png", session.html)
        self.assertEqual(events[-1]["event"], "final")

    def test_large_tool_result_is_previewed_for_the_next_model_turn(self) -> None:
        """The graph must retain raw output outside, not inside, provider history."""
        source = "<section>" + "".join(
            f'<img src="https://cdn.example/{index}.png" alt="image {index}">' for index in range(320)
        ) + "</section>"
        session = HtmlEditSession(source, tool_result_max_tokens=512)
        model = ScriptedChatModel(
            script=[{"tool": ("inspect_current_images", {})}, {"text": "图片清单已读取。"}],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="output-store-run")

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "工具结果测试稿",
                    session.html,
                    "盘点图片",
                    session.document_map(),
                    None,
                    [],
                    None,
                    None,
                    session,
                    None,
                    20_000,
                    "output-store-run",
                    store, tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
        ):
            events = asyncio.run(go())
        try:
            self.assertEqual(events[-1]["event"], "final")
            self.assertGreaterEqual(len(model.seen_messages), 2)
            replayed_tool = next(
                message for message in model.seen_messages[1] if getattr(message, "name", "") == "inspect_current_images"
            )
            payload = json.loads(str(replayed_tool.content))
            self.assertTrue(payload["truncated"])
            self.assertTrue(payload["output_id"].startswith("toolout-"))
            self.assertNotIn('"slot":160', str(replayed_tool.content))
            timeline_result = next(
                event["data"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "inspect_current_images"
            )
            self.assertEqual(timeline_result["model_input"]["state"], "available")
            self.assertTrue(timeline_result["model_input"]["truncated"])
            self.assertEqual(timeline_result["model_input"]["content"], str(replayed_tool.content))
            self.assertNotIn('"slot":160', timeline_result["model_input"]["content"])
            with Session(engine) as db:
                stored = db.get(ChatToolOutput, payload["output_id"])
                self.assertIsNotNone(stored)
                self.assertIn('"slot":320', stored.content)
        finally:
            engine.dispose()

    def test_read_tool_output_continuation_reaches_model_and_timeline(self) -> None:
        """A continuation page is already provider-bounded and must be shown verbatim."""
        session = HtmlEditSession(SOURCE_HTML, tool_result_max_tokens=512)
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="read-output-run")
        source = "完整暂存工具结果。" * 800

        async def go(output_id: str) -> tuple[list[dict[str, Any]], ScriptedChatModel]:
            model = ScriptedChatModel(
                script=[
                    {"tool": ("read_tool_output", {"output_id": output_id, "max_tokens": 512})},
                    {"text": "已读取需要的续读内容。"},
                ],
                seen_message_counts=[],
                seen_messages=[],
            )
            events = [
                event
                async for event in run_agent_loop(
                    model,
                    "工具续读测试稿",
                    session.html,
                    "读取已暂存结果",
                    session.document_map(),
                    None,
                    [],
                    None,
                    None,
                    session,
                    None,
                    20_000,
                    "read-output-run",
                    store, tool_protocol="v1"
                )
            ]
            return events, model

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
        ):
            binding = store.bind(
                tool_call_id="source-call",
                tool_name="read_blocks",
                content=source,
                max_preview_tokens=256,
                force_store=True,
            )
            self.assertIsNotNone(binding.output_id)
            events, model = asyncio.run(go(str(binding.output_id)))
        try:
            replayed_tool = next(
                message
                for message in model.seen_messages[1]
                if isinstance(message, ToolMessage) and message.name == "read_tool_output"
            )
            timeline_result = next(
                event["data"]
                for event in events
                if event["event"] == "tool_result" and event["data"]["name"] == "read_tool_output"
            )
            self.assertEqual(timeline_result["model_input"], {
                "state": "available",
                "content": str(replayed_tool.content),
                "truncated": False,
            })
            self.assertIn("next_cursor", timeline_result["model_input"]["content"])
            self.assertNotEqual(timeline_result["model_input"]["content"], source)
        finally:
            engine.dispose()

    def test_large_theme_library_finishes_before_the_next_model_turn(self) -> None:
        """A theme library uses the same durable-preview path as the production incident."""
        session = HtmlEditSession(
            '<section><h1><span leaf="">旧标题</span></h1><p><span leaf="">正文内容</span></p></section>',
            tool_result_max_tokens=512,
        )
        model = ScriptedChatModel(
            script=[{"tool": ("read_gzh_theme", {})}, {"text": "主题组件已读取。"}],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="theme-output-store-run")
        theme_application = {
            "theme_name": "大型主题测试",
            "apply_mode": "full",
            "user_instructions": "",
            "theme_markdown": ("## 标题组件\n" + ("主题排版内容 " * 96) + "\n") * 180,
        }

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "主题工具结果测试稿",
                    session.html,
                    "应用主题",
                    session.document_map(),
                    None,
                    [],
                    None,
                    None,
                    session,
                    None,
                    20_000,
                    "theme-output-store-run",
                    store,
                    theme_application, tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
        ):
            events = asyncio.run(asyncio.wait_for(go(), timeout=2))
        try:
            theme_result_index = next(
                index
                for index, event in enumerate(events)
                if event["event"] == "tool_result" and event["data"]["name"] == "read_gzh_theme"
            )
            model_start_indexes = [
                index
                for index, event in enumerate(events)
                if event["event"] == "heartbeat" and event["data"].get("phase") == "model_turn_started"
            ]
            self.assertGreaterEqual(len(model_start_indexes), 2)
            self.assertLess(theme_result_index, model_start_indexes[1])
            self.assertEqual(events[-1]["event"], "final")
            self.assertGreaterEqual(len(model.seen_messages), 2)
            replayed_tool = next(
                message for message in model.seen_messages[1] if getattr(message, "name", "") == "read_gzh_theme"
            )
            preview = json.loads(str(replayed_tool.content))
            self.assertTrue(preview["truncated"])
            with Session(engine) as db:
                stored = db.get(ChatToolOutput, preview["output_id"])
                self.assertIsNotNone(stored)
                self.assertIn("主题排版内容", stored.content)
        finally:
            engine.dispose()

    def test_applied_theme_reference_can_be_read_during_a_later_chat(self) -> None:
        """A completed proposal remains a read-only source for local fidelity fixes."""
        session = HtmlEditSession(SOURCE_HTML, tool_result_max_tokens=512)
        model = ScriptedChatModel(
            script=[{"tool": ("read_current_gzh_theme", {})}, {"text": "已按主题参考核对细节。"}],
            seen_message_counts=[],
            seen_messages=[],
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        store = ToolOutputStore(document_id=1, session_id=2, run_id="theme-reference-run")
        theme_reference = {
            "proposal_id": "already-applied-proposal",
            "theme_name": "当前主题测试",
            "apply_mode": "restrained",
            "user_instructions": "标题更醒目",
            "theme_markdown": "SECRET_THEME_COMPONENT\n\n" + ("主题组件内容 " * 3_000),
        }

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "主题参考测试稿",
                    session.html,
                    "标题不够像当前主题，请补齐细节",
                    session.document_map(),
                    None,
                    [],
                    None,
                    None,
                    session,
                    None,
                    20_000,
                    "theme-reference-run",
                    store,
                    None,
                    None,
                    theme_reference, tool_protocol="v1"
                )
            ]

        with (
            patch("app.services.chat_agent.SessionLocal", factory),
            patch("app.services.tool_output_store.SessionLocal", factory),
        ):
            events = asyncio.run(asyncio.wait_for(go(), timeout=2))
        try:
            self.assertEqual(events[-1]["event"], "final")
            self.assertGreaterEqual(len(model.seen_messages), 2)
            system = model.seen_messages[0][0]
            system_text = system.content if isinstance(system.content, str) else system.content[0]["text"]
            self.assertIn("当前主题测试", system_text)
            self.assertNotIn("SECRET_THEME_COMPONENT", system_text)
            replayed_tool = next(
                message
                for message in model.seen_messages[1]
                if getattr(message, "name", "") == "read_current_gzh_theme"
            )
            preview = json.loads(str(replayed_tool.content))
            self.assertTrue(preview["truncated"])
            with Session(engine) as db:
                stored = db.get(ChatToolOutput, preview["output_id"])
                self.assertIsNotNone(stored)
                self.assertIn("SECRET_THEME_COMPONENT", stored.content)
        finally:
            engine.dispose()

    def test_theme_reference_tool_rejects_articles_without_an_applied_theme(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[{"tool": ("read_current_gzh_theme", {})}, {"text": "当前文章没有主题参考。"}],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        result = next(
            event["data"]["result"]
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "read_current_gzh_theme"
        )
        self.assertIn("没有可参考的已应用主题", result)
        self.assertEqual(events[-1]["event"], "final")

    def test_edit_tool_streams_an_html_snapshot_for_live_preview(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=self._patch_script(session), seen_message_counts=[], seen_messages=[]
        )

        events = _run(model, session)

        snapshots = [
            event["data"]["html"]
            for event in events
            if event["event"] == "tool_result" and event["data"].get("html")
        ]
        self.assertTrue(snapshots, "修改工具必须立即推送 HTML 快照，否则预览要等整轮结束")
        self.assertIn("新标题", snapshots[-1])

    def test_streamed_tool_parameters_publish_a_live_token_count(self) -> None:
        """The preparing timeline can replace its static label while args stream."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_html", {"query": "正文内容"})},
                {"text": "已找到对应排版块。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        progress_events = [
            event["data"]
            for event in events
            if event["event"] == "tool_call"
            and event["data"].get("preparing") is True
            and isinstance(event["data"].get("argument_tokens"), int)
        ]
        self.assertTrue(progress_events)
        self.assertGreater(progress_events[-1]["argument_tokens"], 0)

    def test_streamed_patch_parameter_tokens_increase_with_each_fragment(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": ("search_html", {"query": "正文内容和标题"}),
                    "tool_argument_fragments": ['{"query":"正', '文内容和标题"}'],
                    "tool_argument_fragment_delay": 0.3,
                },
                {"text": "已找到对应排版块。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        token_counts = [
            event["data"]["argument_tokens"]
            for event in events
            if event["event"] == "tool_call"
            and event["data"].get("preparing") is True
            and isinstance(event["data"].get("argument_tokens"), int)
        ]
        self.assertGreaterEqual(len(token_counts), 2)
        self.assertGreater(token_counts[-1], token_counts[0])

    def test_ask_user_parameter_tokens_increase_without_a_stream_delay(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "ask_user",
                        {
                            "question": "请选择标题样式",
                            "options": [{"label": "大标题"}, {"label": "小标题"}],
                        },
                    ),
                    "tool_argument_fragments": [
                        '{"question":"请选择标题',
                        '样式","options":[{"label":"大标题"},{"label":"小标题"}]}',
                    ],
                },
                {"text": "收到你的选择。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        token_counts = [
            event["data"]["argument_tokens"]
            for event in events
            if event["event"] == "tool_call"
            and event["data"].get("preparing") is True
            and event["data"].get("name") == "ask_user"
            and isinstance(event["data"].get("argument_tokens"), int)
        ]
        self.assertGreaterEqual(len(token_counts), 2)
        self.assertGreater(token_counts[-1], token_counts[0])

    def test_complete_write_tool_json_does_not_wait_for_provider_stream_close(self) -> None:
        """完整补丁只为终结用量等待有界宽限，网关挂起不能阻止执行。"""
        session = HtmlEditSession(SOURCE_HTML)
        script = self._patch_script(session)
        script[1]["hang_after_tool"] = True
        model = ScriptedChatModel(script=script, seen_message_counts=[], seen_messages=[])

        # This case verifies that a complete write call is dispatched before a
        # gateway's missing terminal frame. Browser-backed compliance is
        # unrelated. Allow graph/schema setup time under the complete suite;
        # the simulated provider hangs for 60 seconds without bounded draining.
        with patch.object(session, "check_compliance", return_value={"isValid": True, "violations": []}), patch(
            "app.services.chat_agent.MODEL_TOOL_TERMINAL_GRACE_SECONDS", 0.01
        ):
            events = _run(model, session, timeout=2.0)

        self.assertEqual(events[-1]["event"], "final")
        self.assertNotIn("error", [event["event"] for event in events])
        self.assertIn("新标题", events[-1]["data"]["html"])

    def test_disconnect_after_text_replays_the_unfinished_model_turn(self) -> None:
        """The browser receives a rollback marker before a new model request replaces partial text."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"text": "断流前的片段", "disconnect_after_text": True},
                {"text": "重试后的完整答复"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        with patch("app.services.chat_agent.MODEL_TURN_RETRY_BASE_SECONDS", 0.001):
            events = _run(model, session)

        self.assertEqual(model.seen_message_counts, [2, 2])
        self.assertIn("model_turn_retry", [event["event"] for event in events])
        self.assertEqual(events[-1]["event"], "final")
        self.assertEqual(events[-1]["data"]["content"], "重试后的完整答复")

    def test_system_prompt_is_sent_once_with_static_half_first(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=self._patch_script(session), seen_message_counts=[], seen_messages=[]
        )

        _run(model, session)

        first_turn = model.seen_messages[0]
        system = first_turn[0]
        text = system.content if isinstance(system.content, str) else system.content[0]["text"]
        self.assertIn("你是一个专业的微信公众号文章排版 Agent", text)
        self.assertLess(text.index("## 工作规则"), len(text))

    def test_tight_budget_still_completes_the_run(self) -> None:
        """run 内压缩必须让长任务跑完，而不是把它压成非法请求。"""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=self._patch_script(session), seen_message_counts=[], seen_messages=[]
        )

        events = _run(model, session, budget=400)

        self.assertEqual(events[-1]["event"], "final")
        self.assertNotIn("error", [event["event"] for event in events])
        self.assertIn("新标题", events[-1]["data"]["html"])
        # 断言压缩真的发生过，否则本用例会随预算变化悄悄退化成「没压也过」。
        compactions = [
            event
            for event in events
            if event["event"] == "context_stats" and event["data"].get("state") == "in_run_compacted"
        ]
        self.assertTrue(compactions, "紧预算下必须触发 run 内压缩")
        self.assertGreater(compactions[-1]["data"]["run_digested_cycles"], 0)

    def test_tool_pairing_holds_in_every_request_actually_sent(self) -> None:
        """压缩后仍不能出现「有 tool_calls 却无对应 tool 结果」的请求。"""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=self._patch_script(session), seen_message_counts=[], seen_messages=[]
        )

        _run(model, session, budget=400)

        for messages in model.seen_messages:
            expected: list[str] = []
            for message in messages:
                for call in getattr(message, "tool_calls", None) or []:
                    expected.append(str(call["id"]))
            answered = [
                str(message.tool_call_id) for message in messages if hasattr(message, "tool_call_id")
            ]
            self.assertEqual(
                sorted(expected), sorted(answered), "每个 tool_call 都必须有且只有一个对应结果"
            )

    def test_task_plan_reaches_the_ui_as_a_plan_activity(self) -> None:
        """计划要经通用 activity 渲染路径抵达前端，每一步都带状态标签。"""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "update_task_plan",
                        {
                            "tasks": [
                                {"step": "改标题", "status": "in_progress"},
                                {"step": "查合规", "status": "pending"},
                            ]
                        },
                    )
                },
                {"text": "计划已登记。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        plans = [
            event
            for event in events
            if event["event"] == "tool_result" and event["data"]["name"] == "update_task_plan"
        ]
        self.assertEqual(len(plans), 1)
        activity = plans[0]["data"]["activity"]
        self.assertEqual(activity["kind"], "plan")
        self.assertEqual(len(activity["targets"]), 2)
        self.assertIn("进行中", activity["targets"][0]["text"])
        self.assertIn("待办", activity["targets"][1]["text"])
        self.assertEqual(
            activity["details"]["tasks"],
            [
                {"step": "改标题", "status": "in_progress"},
                {"step": "查合规", "status": "pending"},
            ],
        )
        self.assertEqual(events[-1]["event"], "final")

    def test_ambiguous_task_plan_is_rejected_without_ending_the_run(self) -> None:
        """两步同时 in_progress 时必须报错让模型改正，而不是终止本轮。"""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "update_task_plan",
                        {
                            "tasks": [
                                {"step": "改标题", "status": "in_progress"},
                                {"step": "查合规", "status": "in_progress"},
                            ]
                        },
                    )
                },
                {"text": "已修正计划。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        errors = [
            event
            for event in events
            if event["event"] == "tool_result" and event["data"]["activity"]["kind"] == "error"
        ]
        self.assertEqual(len(errors), 1)
        self.assertIn("in_progress", errors[0]["data"]["result"])
        # 工具报错是可恢复的，整轮必须继续走到 final。
        self.assertEqual(events[-1]["event"], "final")

    def test_unknown_tool_name_does_not_kill_the_run(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("no_such_tool", {})},
                {"text": "已改用可用工具完成。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        self.assertEqual(events[-1]["event"], "final")
        self.assertFalse(events[-1]["data"]["html_changed"])

    def test_stalled_message_conversion_reports_an_error_after_output(self) -> None:
        """正文已流出时，收尾卡住也必须把控制权还给 API 终态处理器。"""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[{"text": "正文已经输出。"}], seen_message_counts=[], seen_messages=[]
        )

        def block_conversion(*_args: Any) -> None:
            time.sleep(0.2)

        with (
            patch("app.services.chat_agent.MODEL_MESSAGE_CONVERSION_TIMEOUT_SECONDS", 0.1),
            patch("app.services.chat_agent.message_chunk_to_message", side_effect=block_conversion),
        ):
            events = _run(model, session)

        self.assertIn("text_delta", [event["event"] for event in events])
        self.assertEqual(events[-1]["event"], "error")
        self.assertIn("响应整理超过", events[-1]["data"]["message"])

    def test_finishing_without_a_model_compliance_call_does_not_start_the_checker(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[{"text": "正文已经输出。"}], seen_message_counts=[], seen_messages=[]
        )

        with patch.object(session, "check_compliance", side_effect=AssertionError("Unexpected automatic check")) as checker:
            events = _run(model, session)
        checker.assert_not_called()
        self.assertEqual(events[-1]["event"], "final")
        self.assertIsNone(events[-1]["data"]["compliance"])
        self.assertFalse(any(event["event"] in {"tool_call", "tool_result"} for event in events))

    def test_editing_after_a_model_compliance_call_discards_the_old_final_report(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        script = self._patch_script(session)
        model = ScriptedChatModel(
            script=[script[2], script[0], script[1], script[3]],
            seen_message_counts=[],
            seen_messages=[],
        )
        with patch("app.services.chat_agent.run_compliance_check", return_value=SimpleNamespace(to_dict=lambda: {"isValid": True})) as checker:
            events = _run(model, session)

        checker.assert_called_once_with(SOURCE_HTML)
        self.assertEqual(events[-1]["event"], "final")
        self.assertIn("新标题", events[-1]["data"]["html"])
        self.assertIsNone(events[-1]["data"]["compliance"])

    def test_ask_user_pauses_then_resumes_with_the_original_tool_call_id(self) -> None:
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "ask_user",
                        {
                            "question": "标题应该更偏向资讯感还是杂志感？",
                            "options": [
                                {"label": "资讯感", "description": "层次清晰、便于快速浏览"},
                                {"label": "杂志感", "description": "强调留白和视觉节奏"},
                            ],
                            "allow_multiple": False,
                            "include_style": False,
                        },
                    )
                },
                {"text": "已按你确认的排版方向继续处理。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        async def first_pass() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试稿",
                    session.html,
                    "请优化标题排版",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    article_typography_settings={
                        "horizontal_padding_px": 12,
                        "paragraph_spacing_px": 8,
                        "font_size_px": 16,
                        "line_height_em": 1.8,
                        "letter_spacing_px": 0.5,
                        "text_indent_em": 1.5,
                        "text_color": "#123456",
                    }, tool_protocol="v1"
                )
            ]

        paused = asyncio.run(first_pass())
        self.assertEqual([event["event"] for event in paused][-1], "user_question")
        pause_data = paused[-1]["data"]
        self.assertEqual(pause_data["question"]["options"][0]["id"], "option_1")
        self.assertFalse(pause_data["question"]["allow_multiple"])
        self.assertEqual(pause_data["completed_context_events"], [])

        tool_call_id = pause_data["tool_call_id"]
        visible_tool_call = next(
            event["data"] for event in paused if event["event"] == "tool_call" and not event["data"].get("preparing")
        )
        self.assertEqual(visible_tool_call["id"], tool_call_id)
        restored_messages = restore_resume_messages(pause_data["resume_messages"])
        self.assertEqual(restored_messages[-1].tool_calls[0]["id"], tool_call_id)

        async def resumed_pass() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试稿",
                    session.html,
                    "请优化标题排版",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    resume_messages=restored_messages,
                    resume_tool_result={
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(
                            {"action": "selected", "selected_options": [{"id": "option_1", "label": "资讯感"}]},
                            ensure_ascii=False,
                        ),
                    },
                    prior_context_events=pause_data["completed_context_events"],
                    article_typography_settings={
                        "horizontal_padding_px": 12,
                        "paragraph_spacing_px": 8,
                        "font_size_px": 16,
                        "line_height_em": 1.8,
                        "letter_spacing_px": 0.5,
                        "text_indent_em": 1.5,
                        "text_color": "#123456",
                    }, tool_protocol="v1"
                )
            ]

        resumed = asyncio.run(resumed_pass())
        final = resumed[-1]
        self.assertEqual(final["event"], "final")
        self.assertIn("确认的排版方向", final["data"]["content"])
        self.assertIsInstance(model.seen_messages[1][-1], ToolMessage)
        self.assertEqual(model.seen_messages[1][-1].tool_call_id, tool_call_id)
        self.assertIn("font-size:16px", str(model.seen_messages[1][0].content))
        self.assertIn("#123456", str(model.seen_messages[1][0].content))
        ledger = final["data"]["context_events"]
        calls = {
            call["id"]
            for event in ledger
            if event["kind"] == "assistant"
            for call in event["payload"].get("tool_calls", [])
        }
        results = {
            event["payload"]["tool_call_id"]
            for event in ledger
            if event["kind"] == "tool"
        }
        self.assertEqual(calls, results)

    def test_ask_user_can_pause_after_an_html_write(self) -> None:
        """A later design decision may require confirmation after a partial edit."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "replace_document",
                        {
                            "revision": session.document_map()["revision"],
                            "html": "<section><h1>新标题</h1><p>正文内容</p></section>",
                        },
                    )
                },
                {
                    "tool": (
                        "ask_user",
                        {
                            "question": "后续内容希望延续现有节奏还是改为更强的视觉层次？",
                            "options": [{"label": "延续现有节奏"}, {"label": "增强视觉层次"}],
                        },
                    )
                },
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        self.assertTrue(session.edited)
        self.assertIn("新标题", session.html)
        self.assertEqual(events[-1]["event"], "user_question")
        self.assertEqual(events[-1]["data"]["question"]["question"], "后续内容希望延续现有节奏还是改为更强的视觉层次？")
        self.assertIn(
            "replace_document",
            [event["data"].get("name") for event in events if event["event"] == "tool_result"],
        )

    def test_ask_user_normalizes_stable_options_and_rejects_invalid_style_examples(self) -> None:
        question = normalise_user_question(
            "选择封面标题风格",
            [{"label": "稳重", "style_html": "<h1>稳重标题</h1>"}],
            allow_multiple=True,
            include_style=True,
        )

        self.assertEqual(question["options"][0]["id"], "option_1")
        self.assertTrue(question["include_style"])
        self.assertFalse(question["allow_multiple"])
        self.assertEqual(
            len(
                normalise_user_question(
                    "选择标题排版",
                    [{"label": f"选项 {index}"} for index in range(1, 9)],
                    allow_multiple=True,
                    include_style=False,
                )["options"]
            ),
            8,
        )
        with self.assertRaisesRegex(ValueError, "style_html"):
            normalise_user_question(
                "选择封面标题风格",
                [{"label": "稳重"}],
                allow_multiple=False,
                include_style=True,
            )
        with self.assertRaisesRegex(ValueError, "0 至 8"):
            normalise_user_question(
                "选择标题排版",
                [{"label": f"选项 {index}"} for index in range(1, 10)],
                allow_multiple=True,
                include_style=False,
            )

    def test_ask_user_accepts_common_provider_option_wrappers(self) -> None:
        json_string = normalise_user_question(
            "选择标题风格",
            '[{"label":"资讯感"},{"label":"杂志感"}]',
            allow_multiple=False,
            include_style=False,
        )
        self.assertEqual([item["label"] for item in json_string["options"]], ["资讯感", "杂志感"])
        wrapped = normalise_user_question(
            "选择标题风格",
            {"options": {"label": "稳重"}},
            allow_multiple=False,
            include_style=False,
        )
        self.assertEqual(wrapped["options"][0]["label"], "稳重")

    def test_invalid_ask_user_style_example_returns_tool_error_and_recovers(self) -> None:
        """A malformed style sample must be model-recoverable, not terminal."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {
                    "tool": (
                        "ask_user",
                        {
                            "question": "选择标题风格",
                            "options": [{"label": "杂志感"}],
                            "include_style": True,
                        },
                    )
                },
                {
                    "tool": (
                        "ask_user",
                        {
                            "question": "选择标题风格",
                            "options": [{"label": "杂志感", "style_html": "<h1>杂志感标题</h1>"}],
                            "include_style": True,
                        },
                    )
                },
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        self.assertEqual(events[-1]["event"], "user_question")
        invalid_result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"].get("id") == "call-1"
        )
        self.assertEqual(invalid_result["name"], "ask_user")
        self.assertIn("style_html", invalid_result["result"])
        self.assertEqual(invalid_result["activity"]["kind"], "error")
        self.assertIsInstance(model.seen_messages[1][-1], ToolMessage)
        self.assertEqual(model.seen_messages[1][-1].tool_call_id, "call-1")
        self.assertEqual(invalid_result["model_input"]["state"], "available")
        self.assertEqual(invalid_result["model_input"]["content"], str(model.seen_messages[1][-1].content))
        self.assertEqual(events[-1]["data"]["tool_call_id"], "call-2")

    def test_repeated_invalid_ask_user_degrades_to_a_text_question(self) -> None:
        """An incapable provider cannot spin forever on malformed options."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("ask_user", {"question": "第一问", "options": "不是数组"})},
                {"tool": ("ask_user", {"question": "第二问", "options": "仍然不是数组"})},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        events = _run(model, session)

        self.assertEqual(events[-1]["event"], "user_question")
        self.assertEqual(events[-1]["data"]["tool_call_id"], "call-2")
        self.assertEqual(events[-1]["data"]["question"]["question"], "第二问")
        self.assertEqual(events[-1]["data"]["question"]["options"], [])
        first_error = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"].get("id") == "call-1"
        )
        self.assertIn("选项数量", first_error["result"])

    def test_timeout_answer_allows_a_new_independent_user_question(self) -> None:
        """A timeout guides the model but never disables the ask_user tool."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("ask_user", {"question": "正文需要加入引语样式吗？", "options": [{"label": "加入"}, {"label": "不加入"}]})},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        async def go() -> list[dict[str, Any]]:
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "端到端测试稿",
                    session.html,
                    "把标题改成《新标题》",
                    session.document_map(),
                    None,
                    [],
                    None,
                    None,
                    session,
                    None,
                    0,
                    resume_messages=[
                        AIMessage(
                            content="",
                            tool_calls=[
                                {"name": "ask_user", "args": {"question": "请选择"}, "id": "call-timeout", "type": "tool_call"}
                            ],
                        )
                    ],
                    resume_tool_result={
                        "tool_call_id": "call-timeout",
                        "content": json.dumps({"action": "no_response"}, ensure_ascii=False),
                    }, tool_protocol="v1"
                )
            ]

        events = asyncio.run(go())

        self.assertEqual(events[-1]["event"], "user_question")
        self.assertEqual(events[-1]["data"]["tool_call_id"], "call-1")
        self.assertEqual(events[-1]["data"]["question"]["question"], "正文需要加入引语样式吗？")
        self.assertIsInstance(model.seen_messages[0][-1], ToolMessage)
        self.assertEqual(model.seen_messages[0][-1].tool_call_id, "call-timeout")
        self.assertEqual(json.loads(str(model.seen_messages[0][-1].content))["action"], "no_response")

    def test_unhandled_tool_exception_is_returned_to_the_model(self) -> None:
        """A tool implementation fault remains a recoverable model turn."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("search_html", {"query": "旧标题"})},
                {"text": "读取工具暂不可用，已改用其他方式继续。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        with patch.object(session, "search", side_effect=RuntimeError("临时索引服务不可用")):
            events = _run(model, session)

        self.assertEqual(events[-1]["event"], "final")
        error_result = next(
            event["data"]
            for event in events
            if event["event"] == "tool_result" and event["data"].get("id") == "call-1"
        )
        self.assertIn("临时索引服务不可用", error_result["result"])
        self.assertEqual(error_result["activity"]["kind"], "error")
        self.assertIsInstance(model.seen_messages[1][-1], ToolMessage)
        self.assertEqual(model.seen_messages[1][-1].tool_call_id, "call-1")
        self.assertEqual(error_result["model_input"]["state"], "available")
        self.assertEqual(error_result["model_input"]["content"], str(model.seen_messages[1][-1].content))

    def test_ask_user_can_pause_and_resume_for_three_rounds(self) -> None:
        """Each answered question may lead to another independent question."""
        session = HtmlEditSession(SOURCE_HTML)
        model = ScriptedChatModel(
            script=[
                {"tool": ("ask_user", {"question": "第一项偏好？", "options": []})},
                {"tool": ("ask_user", {"question": "第二项偏好？", "options": [{"label": "A"}]})},
                {
                    "tool": (
                        "ask_user",
                        {
                            "question": "第三项偏好？",
                            "options": [
                                {"label": "A", "style_html": "<h1>A</h1>"},
                                {"label": "B", "style_html": "<h1>B</h1>"},
                            ],
                            "include_style": True,
                        },
                    )
                },
                {"text": "三轮偏好都已确认，继续完成排版。"},
            ],
            seen_message_counts=[],
            seen_messages=[],
        )

        async def run_pass(
            pause: dict[str, Any] | None = None,
        ) -> list[dict[str, Any]]:
            kwargs: dict[str, Any] = {}
            if pause is not None:
                kwargs = {
                    "resume_messages": restore_resume_messages(pause["resume_messages"]),
                    "resume_tool_result": {
                        "tool_call_id": pause["tool_call_id"],
                        "content": json.dumps({"action": "skipped"}, ensure_ascii=False),
                    },
                    "prior_context_events": pause["completed_context_events"],
                }
            return [
                event
                async for event in run_agent_loop(
                    model,
                    "测试稿",
                    session.html,
                    "请逐项确认排版偏好",
                    session.document_map(),
                    None,
                    [],
                    session=session,
                    **kwargs, tool_protocol="v1"
                )
            ]

        first = asyncio.run(run_pass())
        second = asyncio.run(run_pass(first[-1]["data"]))
        third = asyncio.run(run_pass(second[-1]["data"]))
        final = asyncio.run(run_pass(third[-1]["data"]))

        self.assertEqual([events[-1]["event"] for events in [first, second, third]], ["user_question"] * 3)
        self.assertEqual(final[-1]["event"], "final")
        question_call_ids = [
            first[-1]["data"]["tool_call_id"],
            second[-1]["data"]["tool_call_id"],
            third[-1]["data"]["tool_call_id"],
        ]
        self.assertEqual(question_call_ids, ["call-1", "call-2", "call-3"])
        ledger = final[-1]["data"]["context_events"]
        calls = {
            call["id"]
            for event in ledger
            if event["kind"] == "assistant"
            for call in event["payload"].get("tool_calls", [])
        }
        results = {
            event["payload"]["tool_call_id"]
            for event in ledger
            if event["kind"] == "tool"
        }
        self.assertEqual(calls, set(question_call_ids))
        self.assertEqual(results, set(question_call_ids))


if __name__ == "__main__":
    unittest.main()
