"""Regression coverage for Cline-style cross-turn event replay."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.services.agent_context import (
    AgentContextBuilder,
    COMPACTION_TARGET_TOKENS,
    CompactionModelError,
    ContextRecord,
    _normalise_memory,
)
from app.services.chat_agent import serialise_context_events
from app.services.html_workspace import HtmlWorkspace


class ContextEventLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.model = AIModel(
            provider_id=1,
            model_name="test",
            display_name="test",
            context_window_tokens=16_000,
            context_compaction_threshold_tokens=12_000,
            max_output_tokens=1_000,
            tool_result_max_tokens=800,
        )
        self.session = ChatSession(document_id=1, title="测试")
        self.db.add_all([self.model, self.session])
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def add_event(self, kind: ContextEventKind, payload: dict, ordinal: int, revision: str = "") -> None:
        # A canonical ledger event always belongs to a concrete chat message.
        # Tests must model that relationship too, otherwise an orphaned event
        # could accidentally bypass re-ask archive visibility checks.
        message = ChatMessage(
            document_id=1,
            session_id=self.session.id,
            role=MessageRole.USER if kind == ContextEventKind.USER else MessageRole.ASSISTANT,
            content=str(payload.get("content", "")),
        )
        self.db.add(message)
        self.db.flush()
        self.db.add(
            ChatContextEvent(
                document_id=1,
                session_id=self.session.id,
                message_id=message.id,
                ordinal=0,
                kind=kind,
                payload_json=json.dumps(payload, ensure_ascii=False),
                document_revision=revision,
            )
        )

    def builder(self, request: str = "继续完成") -> AgentContextBuilder:
        workspace = HtmlWorkspace("<section><h1>当前标题</h1><p>当前正文</p></section>")
        return AgentContextBuilder(
            self.db,
            1,
            self.session.id,
            self.model,
            workspace,
            [],
            "系统规则",
            request,
        )

    def test_replays_full_tool_pair_across_user_turns(self) -> None:
        self.add_event(ContextEventKind.USER, {"content": "先定位标题"}, 1)
        self.add_event(
            ContextEventKind.ASSISTANT,
            {"content": "", "tool_calls": [{"id": "call-1", "name": "read_blocks", "args": {"block_ids": ["old"]}}]},
            2,
        )
        self.add_event(
            ContextEventKind.TOOL,
            {"content": '{"revision":"old","blocks":["x"]}', "tool_call_id": "call-1", "name": "read_blocks", "status": "success"},
            3,
            revision="old",
        )
        self.add_event(ContextEventKind.ASSISTANT, {"content": "标题已找到"}, 4)
        self.db.commit()

        prepared = asyncio.run(self.builder().prepare())

        self.assertEqual([type(message) for message in prepared.history], [HumanMessage, AIMessage, ToolMessage, AIMessage])
        self.assertIn('"stale": true', prepared.history[2].content)
        self.assertNotIn('"old"', prepared.history[2].content)
        self.assertEqual(prepared.stats["tool_full_replayed_count"], 1)
        self.assertGreater(prepared.stats["used_tokens"], prepared.stats["conversation_tokens"] - 100)

    def test_summary_source_refs_require_real_event_or_tool_output_ids(self) -> None:
        memory = _normalise_memory(
            {
                "source_refs": [
                    "event:42",
                    "tool:get_document_map",
                    "tool:toolout-123e4567-e89b-12d3-a456-426614174000",
                    "event:not-an-id",
                ]
            }
        )
        tool_record = ContextRecord(
            id=43,
            message_id=7,
            kind=ContextEventKind.TOOL.value,
            payload={
                "name": "read_blocks",
                "content": json.dumps(
                    {"output_id": "toolout-123e4567-e89b-12d3-a456-426614174000"}
                ),
            },
        )

        self.assertEqual(
            memory["source_refs"],
            ["event:42", "tool:toolout-123e4567-e89b-12d3-a456-426614174000"],
        )
        self.assertIn("[event:43]", tool_record.compact_line())
        self.assertIn("[tool:toolout-123e4567-e89b-12d3-a456-426614174000]", tool_record.compact_line())

    class _SummaryModel:
        async def ainvoke(self, _messages):
            return AIMessage(content=json.dumps({
                "objective": "继续当前排版任务",
                "important_details": ["较早定位必须重新读取"],
                "user_preferences": ["保持简洁"],
                "completed_intents": ["已完成旧任务"],
                "active_work": ["处理当前回合"],
                "pending_tasks": ["继续当前任务"],
                "blocked": [],
                "next_move": ["读取当前文档"],
                "relevant_files": [],
                "source_refs": [],
                "narrative": "旧任务已压缩",
            }, ensure_ascii=False))

    def test_automatic_compaction_uses_event_boundary_and_model_snapshot(self) -> None:
        ordinal = 1
        for turn in range(18):
            self.add_event(ContextEventKind.USER, {"content": f"任务 {turn} " + "需求" * 260}, ordinal)
            ordinal += 1
            self.add_event(ContextEventKind.ASSISTANT, {"content": f"结果 {turn} " + "说明" * 260}, ordinal)
            ordinal += 1
        self.db.commit()

        builder = self.builder()
        preview = builder.snapshot()
        self.assertTrue(preview["requires_compaction"])
        self.assertGreaterEqual(preview["raw_input_tokens"], self.model.context_compaction_threshold_tokens)
        self.assertEqual(preview["active_context_threshold_tokens"], self.model.context_compaction_threshold_tokens)
        self.assertEqual(preview["compiled_input_tokens"], preview["raw_input_tokens"])
        self.assertLess(preview["projected_used_tokens"], preview["raw_input_tokens"])
        self.assertEqual(
            preview["compaction_target_tokens"],
            min(self.model.context_compaction_threshold_tokens, COMPACTION_TARGET_TOKENS),
        )

        prepared = asyncio.run(builder.prepare(self._SummaryModel()))
        snapshot = self.db.query(ChatContextSnapshot).one()
        self.assertEqual(snapshot.strategy, "agentic")
        self.assertGreater(snapshot.compacted_through_event_id, 0)
        self.assertTrue(snapshot.source_prefix_hash.startswith("sha256:"))
        self.assertLessEqual(prepared.stats["used_tokens"], self.model.context_compaction_threshold_tokens)
        self.assertTrue(prepared.history)
        self.assertIsInstance(prepared.history[0], HumanMessage)

    def test_serialization_discards_orphan_tool_call(self) -> None:
        orphan = AIMessage(content="", tool_calls=[{"id": "orphan", "name": "read_blocks", "args": {}}])
        complete = AIMessage(content="", tool_calls=[{"id": "ok", "name": "search_html", "args": {"query": "标题"}}])
        result = serialise_context_events(
            [orphan, complete, ToolMessage(content="{}", tool_call_id="ok", name="search_html")]
        )
        calls = [item for item in result if item["kind"] == "assistant"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["payload"]["tool_calls"][0]["id"], "ok")

    def test_serialization_drops_partially_answered_tool_group(self) -> None:
        partial = AIMessage(
            content="",
            tool_calls=[
                {"id": "first", "name": "search_html", "args": {}},
                {"id": "second", "name": "read_blocks", "args": {}},
            ],
        )

        result = serialise_context_events(
            [partial, ToolMessage(content="{}", tool_call_id="first", name="search_html")]
        )

        self.assertEqual(result, [])

    def test_serialization_drops_duplicate_provider_tool_call_id(self) -> None:
        duplicate_ids = AIMessage(
            content="",
            tool_calls=[
                {"id": "same", "name": "search_html", "args": {}},
                {"id": "same", "name": "read_blocks", "args": {}},
            ],
        )

        result = serialise_context_events(
            [duplicate_ids, ToolMessage(content="{}", tool_call_id="same", name="search_html")]
        )

        self.assertEqual(result, [])

    def test_huge_single_history_turn_can_be_summarized_without_a_partial_tail(self) -> None:
        self.add_event(ContextEventKind.USER, {"content": "payload " * 25_000}, 1)
        self.db.commit()

        builder = self.builder()
        older, retained = builder._partition_for_compaction(builder.records, {})

        self.assertEqual(len(older), 1)
        self.assertEqual(retained, [])

    def test_legacy_current_document_tool_result_is_always_stale_for_replay(self) -> None:
        self.add_event(ContextEventKind.USER, {"content": "读取标题"}, 1)
        self.add_event(
            ContextEventKind.ASSISTANT,
            {"content": "", "tool_calls": [{"id": "legacy-call", "name": "read_blocks", "args": {}}]},
            2,
        )
        event = self.db.query(ChatContextEvent).order_by(ChatContextEvent.id.desc()).first()
        event.is_legacy = True
        self.add_event(
            ContextEventKind.TOOL,
            {
                "content": '{"revision":"legacy-revision","blocks":[{"block_id":"legacy-block"}]}',
                "tool_call_id": "legacy-call",
                "name": "read_blocks",
                "status": "success",
            },
            3,
        )
        tool_event = self.db.query(ChatContextEvent).order_by(ChatContextEvent.id.desc()).first()
        tool_event.is_legacy = True
        self.db.commit()

        prepared = asyncio.run(self.builder().prepare())
        tool_message = next(message for message in prepared.history if isinstance(message, ToolMessage))

        self.assertIn('"stale": true', tool_message.content)
        self.assertNotIn("legacy-revision", tool_message.content)
        self.assertNotIn("legacy-block", tool_message.content)

    def test_model_summary_success_and_failure_leave_raw_events_intact(self) -> None:
        for turn in range(18):
            self.add_event(ContextEventKind.USER, {"content": f"请求 {turn} " + "内容" * 260}, turn * 2 + 1)
            self.add_event(ContextEventKind.ASSISTANT, {"content": f"完成 {turn} " + "结果" * 260}, turn * 2 + 2)
        self.db.commit()
        raw_count = self.db.query(ChatContextEvent).count()

        prepared = asyncio.run(self.builder().prepare(self._SummaryModel()))
        snapshot = self.db.query(ChatContextSnapshot).one()
        self.assertEqual(snapshot.strategy, "agentic")
        self.assertEqual(self.db.query(ChatContextEvent).count(), raw_count)
        self.assertEqual(prepared.memory["user_preferences"], ["保持简洁"])

        snapshot.is_active = False
        snapshot.invalidation_reason = "test"
        self.db.commit()

        class FailingSummaryModel:
            async def ainvoke(self, _messages):
                raise TimeoutError("summary timed out")

        with self.assertRaisesRegex(CompactionModelError, "未返回，可重试"):
            asyncio.run(self.builder().prepare(FailingSummaryModel()))
        self.assertEqual(self.db.query(ChatContextSnapshot).count(), 1)
        self.assertEqual(self.db.query(ChatContextEvent).count(), raw_count)

    def test_invalid_or_timed_out_model_summary_never_uses_deterministic_fallback(self) -> None:
        for turn in range(18):
            self.add_event(ContextEventKind.USER, {"content": f"请求 {turn} " + "内容" * 260}, turn * 2 + 1)
            self.add_event(ContextEventKind.ASSISTANT, {"content": f"完成 {turn} " + "结果" * 260}, turn * 2 + 2)
        self.db.commit()

        class InvalidSummaryModel:
            async def ainvoke(self, _messages):
                return AIMessage(content='{"completed_intents":"not a list"}')

        with self.assertRaisesRegex(CompactionModelError, "无效摘要，可重试"):
            asyncio.run(self.builder().prepare(InvalidSummaryModel()))
        self.assertIsNone(self.db.query(ChatContextSnapshot).first())

        class SlowSummaryModel:
            async def ainvoke(self, _messages):
                await asyncio.sleep(1)
                return AIMessage(content="{}")

        with patch("app.services.agent_context.COMPACTION_MODEL_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(CompactionModelError, "未返回，可重试"):
                asyncio.run(self.builder().prepare(SlowSummaryModel()))
        self.assertIsNone(self.db.query(ChatContextSnapshot).first())

    def test_checkpoint_write_retries_after_transient_database_error(self) -> None:
        for turn in range(18):
            self.add_event(ContextEventKind.USER, {"content": f"请求 {turn} " + "内容" * 260}, turn * 2 + 1)
            self.add_event(ContextEventKind.ASSISTANT, {"content": f"完成 {turn} " + "结果" * 260}, turn * 2 + 2)
        self.db.commit()
        commit = self.db.commit
        attempts = 0

        def flaky_commit() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError("COMMIT", {}, OSError("temporary disconnect"))
            commit()

        with patch.object(self.db, "commit", side_effect=flaky_commit):
            asyncio.run(self.builder().prepare(self._SummaryModel()))

        self.assertEqual(attempts, 2)
        self.assertEqual(self.db.query(ChatContextSnapshot).one().strategy, "agentic")


if __name__ == "__main__":
    unittest.main()
