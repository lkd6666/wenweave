"""Resource regressions must preserve the provider-visible transcript."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.services import agent_context, chat_agent
from app.services.agent_context import AgentContextBuilder
from app.services.chat_images import image_content_blocks
from app.services.html_workspace import HtmlWorkspace
from tests.test_agent_loop_end_to_end import SOURCE_HTML, ScriptedChatModel, _run


class ContextLoadingPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.session = ChatSession(document_id=1, title="resource test")
        self.model = AIModel(provider_id=1, model_name="test", display_name="test",
                             context_window_tokens=64_000, context_compaction_threshold_tokens=50_000,
                             max_output_tokens=2_000, tool_result_max_tokens=4_000)
        self.db.add_all([self.session, self.model])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_message(self, content, **kwargs):
        row = ChatMessage(document_id=1, session_id=self.session.id,
                          role=MessageRole.USER, content=content, **kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def builder(self, **kwargs):
        return AgentContextBuilder(self.db, 1, self.session.id, self.model,
                                   HtmlWorkspace("<p>正文</p>"), None, "规则", **kwargs)

    def test_long_preflight_tokenizes_history_linearly_and_reuses_counts_for_prepare(self):
        for index in range(80):
            self.add_message(f"请调整第 {index} 段。" + "保留文字。" * 10)
        builder = self.builder()
        with patch.object(agent_context, "estimate_tokens", wraps=agent_context.estimate_tokens) as estimate:
            before = builder.snapshot()
            prepared = asyncio.run(builder.prepare())
        # A suffix-by-suffix scan used thousands of calls for these 80 turns.
        self.assertLess(estimate.call_count, 120)
        self.assertEqual(prepared.stats["used_tokens"], before["used_tokens"])
        self.assertEqual(prepared.stats["breakdown"], before["breakdown"])
        self.assertEqual([item.content for item in prepared.history], [item.content for item in builder.records])

    def test_ledger_and_legacy_queries_omit_large_ui_columns(self):
        row = self.add_message("保留原文", html_before="x" * 100_000, html_after="y" * 100_000,
                               reasoning_trace_json='{"content":"private reasoning"}')
        row_id = row.id
        for use_ledger in (False, True):
            if use_ledger:
                self.db.add(ChatContextEvent(document_id=1, session_id=self.session.id, message_id=row_id,
                                             ordinal=0, kind=ContextEventKind.USER,
                                             payload_json=json.dumps({"content": "保留原文"})))
                self.db.flush()
            statements = []
            def capture(_conn, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)
            event.listen(self.engine, "before_cursor_execute", capture)
            try:
                history = asyncio.run(self.builder().prepare()).history
            finally:
                event.remove(self.engine, "before_cursor_execute", capture)
            self.assertEqual(history[0].content, "保留原文")
            projections = "\n".join(sql.split("FROM", 1)[0] for sql in statements if sql.startswith("SELECT"))
            for column in ("html_before", "html_after", "reasoning_trace_json", "tool_calls_json", "turn_blocks_json"):
                self.assertNotIn(column, projections)
            if use_ledger:
                self.assertNotIn("chat_messages.content", projections)

    def test_lazy_legacy_load_respects_branch_and_request_boundaries(self):
        old = self.add_message("截断前")
        self.session.context_start_message_id = old.id
        self.add_message("已回退分支", is_superseded=True)
        kept = self.add_message("保留附图")
        self.db.add(ChatMessage(document_id=1, session_id=self.session.id + 1,
                                role=MessageRole.USER, content="其他会话"))
        current = self.add_message("本次请求")
        self.db.add(ChatImageAttachment(id="image-1", document_id=1, uploader_id=1, message_id=kept.id,
                                       filename="test.png", content_type="image/png", size=4,
                                       storage_mode="local", object_key="images/test.png"))
        self.db.flush()
        history = asyncio.run(self.builder(exclude_message_id=current.id).prepare()).history
        self.assertEqual(len(history), 1)
        self.assertIn("保留附图", history[0].content)
        self.assertIn("attachment_id=image-1", history[0].content)

    def test_prepare_preserves_shared_image_references_without_pixel_io(self):
        self.model.is_multimodal = True
        for index in range(2):
            row = self.add_message(f"图片请求 {index}")
            self.db.add(ChatImageAttachment(id=f"image-{index}", document_id=1, uploader_id=1, message_id=row.id,
                                           filename="test.png", content_type="image/png", size=4,
                                           storage_mode="local", object_key="images/shared.png"))
        self.db.flush()
        builder = self.builder()
        with patch("app.services.chat_images.read_attachment_bytes", return_value=b"pixels") as read:
            first = asyncio.run(builder.prepare()).history
            read.assert_not_called()
            second = asyncio.run(builder.prepare()).history
            read.assert_not_called()
        self.assertEqual(len(first), 2)
        for index, message in enumerate(first):
            self.assertIsInstance(message.content, str)
            self.assertIn(f"attachment_id=image-{index}", message.content)
            self.assertIn(f'url="/api/documents/1/chat-images/image-{index}/content"', message.content)
            self.assertEqual(message.content, second[index].content)


class RuntimeResourceTests(unittest.TestCase):
    def test_system_prompt_reuse_refreshes_after_document_write(self):
        session = chat_agent.HtmlEditSession(SOURCE_HTML)
        updated = "<section><h1>新的稿件标题</h1><p>修订后的文字</p></section>"
        model = ScriptedChatModel(script=[
            {"tool": ("get_document_map", {})},
            {"tool": ("replace_document", {"revision": session.workspace().revision, "html": updated})},
            {"text": "已完成"},
        ], seen_messages=[], seen_message_counts=[])
        with (
            patch.object(chat_agent, "build_system_message", wraps=chat_agent.build_system_message) as build,
            patch.object(HtmlWorkspace, "image_inventory", side_effect=AssertionError("No selection needs no image scan")),
        ):
            _run(model, session)
        self.assertEqual(session.html, updated)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(model.seen_messages[0][0].content, model.seen_messages[1][0].content)
        self.assertIn("修订后的文字", str(model.seen_messages[2][0].content))
        self.assertNotEqual(model.seen_messages[1][0].content, model.seen_messages[2][0].content)

    def test_system_prompt_refreshes_when_tool_budget_changes(self):
        session = chat_agent.HtmlEditSession("<section>" + "".join(
            f"<p>第 {index} 段，需要保留的详细正文</p>" for index in range(100)
        ) + "</section>")
        async def run():
            model = ScriptedChatModel(script=[{"tool": ("get_document_map", {})}, {"text": "已完成"}],
                                      seen_messages=[], seen_message_counts=[])
            async for item in chat_agent.run_agent_loop(model, "稿件", session.html, "检查", session.document_map(),
                                                        None, [], session=session, tool_protocol="v1"):
                if item["event"] == "tool_result":
                    session.set_effective_tool_result_limit(512)
            return model
        with patch.object(chat_agent, "build_system_message", wraps=chat_agent.build_system_message) as build:
            model = asyncio.run(run())
        self.assertGreaterEqual(build.call_count, 2)
        self.assertLess(len(model.seen_messages[-1][0].content), len(model.seen_messages[0][0].content))
        expected = chat_agent.build_system_message(model, "稿件", session.html,
                                                   session.workspace().map_payload(tool_result_max_tokens=512))
        self.assertEqual(model.seen_messages[-1][0].content, expected.content)

    def test_image_cache_isolates_storage_and_provider_and_returns_independent_blocks(self):
        cache = {}
        first = SimpleNamespace(id="1", storage_mode="local", object_key="shared.png", content_type="image/png")
        other = SimpleNamespace(id="2", storage_mode="oss", object_key="shared.png", content_type="image/png")
        with patch("app.services.chat_images.read_attachment_bytes", return_value=b"pixels") as read:
            blocks = image_content_blocks(None, [first, first], provider_type="openai_compatible",
                                          include_images=True, content_cache=cache)
            self.assertEqual(read.call_count, 1)
            self.assertIs(blocks[0]["image_url"]["url"], blocks[1]["image_url"]["url"])
            blocks[0]["image_url"]["url"] = "modified"
            self.assertEqual(blocks[1]["image_url"]["url"], "data:image/png;base64,cGl4ZWxz")
            image_content_blocks(None, [other], provider_type="openai_compatible", include_images=True, content_cache=cache)
            anthropic = image_content_blocks(None, [first], provider_type="anthropic", include_images=True, content_cache=cache)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(anthropic[0]["source"]["data"], "cGl4ZWxz")
