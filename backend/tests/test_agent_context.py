import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.api.routes.chat import (
    _context_compaction_event_data,
    _context_compaction_notice_content,
    _merge_runtime_context_stats,
    _persist_context_compaction_notice,
    _persist_runtime_compaction_snapshot,
)
from app.bootstrap import _legacy_snapshot_prefix_hash
from app.models.ai_model import AIModel
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_session import ChatSession, ChatSessionMemory
from app.db.base import Base
from app.services.agent_context import AgentContextBuilder, COMPACTION_TARGET_TOKENS, ContextRecord, context_prefix_hash
from app.services.chat_agent import _runtime_context_stats_for_messages
from app.services.html_workspace import HtmlWorkspace
from app.schemas.ai_provider import ModelCreate


class AgentContextBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.model = AIModel(
            provider_id=1,
            model_name="test-model",
            display_name="Test",
            context_window_tokens=32768,
            context_compaction_threshold_tokens=16000,
            max_output_tokens=1000,
            tool_result_max_tokens=1000,
        )
        self.db.add(self.model)
        self.session = ChatSession(document_id=1, title="上下文测试")
        self.db.add(self.session)
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def add_turn(self, text: str, role: MessageRole) -> ChatMessage:
        message = ChatMessage(document_id=1, session_id=self.session.id, role=role, content=text)
        self.db.add(message)
        self.db.flush()
        return message

    def builder(self, rows: list[ChatMessage], prompt: str = "规则") -> AgentContextBuilder:
        return AgentContextBuilder(
            self.db,
            1,
            self.session.id,
            self.model,
            HtmlWorkspace("<section><h1>标题</h1><p>正文</p></section>"),
            rows,
            prompt,
        )

    class _Compactor:
        async def ainvoke(self, _messages):
            return AIMessage(content=json.dumps({
                "objective": "继续完成排版任务",
                "important_details": ["历史内容仅作语义线索"],
                "user_preferences": ["保持现有文案"],
                "completed_intents": ["已完成早期排版"],
                "active_work": ["压缩早期历史"],
                "pending_tasks": ["继续处理最近回合"],
                "blocked": [],
                "next_move": ["重新读取当前文档"],
                "relevant_files": [],
                "source_refs": [],
                "narrative": "模型生成的会话工作摘要",
            }, ensure_ascii=False))

    def test_short_history_is_replayed_without_compaction(self) -> None:
        rows = [self.add_turn("请调整标题颜色", MessageRole.USER), self.add_turn("已完成", MessageRole.ASSISTANT)]

        prepared = asyncio.run(self.builder(rows).prepare())

        self.assertEqual(len(prepared.history), 2)
        self.assertEqual(prepared.stats["state"], "ready")
        self.assertIsNone(self.db.query(ChatSessionMemory).first())

    def test_large_input_window_compacts_back_to_twenty_thousand_tokens(self) -> None:
        self.model.context_window_tokens = 258_000
        self.model.context_compaction_threshold_tokens = 176_000
        self.model.max_output_tokens = 82_000

        stats = self.builder([]).snapshot()

        self.assertEqual(stats["compaction_target_tokens"], COMPACTION_TARGET_TOKENS)

    def test_compaction_can_exceed_the_soft_target_to_keep_the_newest_complete_turn(self) -> None:
        self.model.context_window_tokens = 258_000
        self.model.context_compaction_threshold_tokens = 176_000
        self.model.max_output_tokens = 82_000
        rows = [
            self.add_turn("早期任务", MessageRole.USER),
            self.add_turn("早期结果", MessageRole.ASSISTANT),
            self.add_turn("近期任务 " + "detail " * 15_000, MessageRole.USER),
        ]
        builder = self.builder(rows)
        records = builder._source_records()

        older, retained = builder._partition_for_compaction(records, {})

        self.assertEqual(older, records[:2])
        self.assertEqual(retained, records[2:])

    def test_migration_prefix_hash_matches_live_enum_value(self) -> None:
        event = ChatContextEvent(
            document_id=1,
            session_id=self.session.id,
            message_id=self.add_turn("旧请求", MessageRole.USER).id,
            ordinal=0,
            kind=ContextEventKind.USER,
            payload_json='{"content":"旧请求"}',
            document_revision="rev-1",
        )
        self.db.add(event)
        self.db.flush()
        record = ContextRecord(
            id=event.id,
            message_id=event.message_id,
            kind=event.kind.value,
            payload=event.payload,
            document_revision=event.document_revision,
            is_legacy=event.is_legacy,
        )

        migrated = _legacy_snapshot_prefix_hash([
            {
                "id": event.id,
                "message_id": event.message_id,
                "kind": "USER",
                "payload_json": event.payload_json,
                "document_revision": event.document_revision,
                "is_legacy": event.is_legacy,
            }
        ])

        self.assertEqual(migrated, context_prefix_hash([record]))

    def test_long_history_uses_model_snapshot_and_keeps_recent_turns(self) -> None:
        rows: list[ChatMessage] = []
        for index in range(20):
            rows.append(self.add_turn(f"用户偏好 {index} " + "内容" * 900, MessageRole.USER))
            rows.append(self.add_turn(f"已完成第 {index} 轮 " + "结果" * 900, MessageRole.ASSISTANT))

        builder = self.builder(rows, "规则" * 1200)
        before = builder.snapshot()
        prepared = asyncio.run(builder.prepare(self._Compactor()))

        self.assertEqual(prepared.stats["state"], "compacted")
        # New policy retains complete recent turns when they fit the input
        # budget, even when that means slightly exceeding the soft 20K target.
        self.assertLess(len(prepared.history), len(rows))
        self.assertEqual(prepared.stats["conversation_message_count"], len(rows))
        self.assertEqual(prepared.stats["conversation_tokens"], before["conversation_tokens"])
        self.assertGreater(prepared.stats["compacted_history_message_count"], 0)
        self.assertGreater(prepared.stats["compacted_history_tokens"], 0)
        self.assertLess(prepared.stats["used_tokens"], before["used_tokens"])
        snapshot = self.db.query(ChatContextSnapshot).one()
        summary = json.loads(snapshot.summary_json)
        self.assertIn("user_preferences", summary)
        self.assertNotIn("<section", snapshot.summary_json)

    def test_compaction_failure_does_not_write_a_snapshot(self) -> None:
        rows: list[ChatMessage] = []
        for index in range(20):
            rows.append(self.add_turn(f"用户任务 {index} " + "内容" * 900, MessageRole.USER))
            rows.append(self.add_turn(f"处理结果 {index} " + "结果" * 900, MessageRole.ASSISTANT))

        with self.assertRaisesRegex(Exception, "压缩模型不可用"):
            asyncio.run(self.builder(rows, "规则" * 1200).prepare())
        self.assertIsNone(self.db.query(ChatContextSnapshot).first())

    def test_completed_runtime_compaction_promotes_only_a_complete_source_to_snapshot(self) -> None:
        user = self.add_turn("请继续调整", MessageRole.USER)
        assistant = self.add_turn("处理中", MessageRole.ASSISTANT)
        user_event = ChatContextEvent(
            document_id=1, session_id=self.session.id, message_id=user.id, ordinal=0,
            kind=ContextEventKind.USER, payload_json='{"content":"请继续调整"}',
        )
        assistant_event = ChatContextEvent(
            document_id=1, session_id=self.session.id, message_id=assistant.id, ordinal=0,
            kind=ContextEventKind.ASSISTANT,
            payload_json='{"content":"","tool_calls":[{"id":"call-1","name":"read_blocks","args":{}}]}',
        )
        tool_event = ChatContextEvent(
            document_id=1, session_id=self.session.id, message_id=assistant.id, ordinal=1,
            kind=ContextEventKind.TOOL,
            payload_json='{"content":"{\\"ok\\":true}","tool_call_id":"call-1","name":"read_blocks"}',
        )
        self.db.add_all([user_event, assistant_event, tool_event])
        self.db.flush()
        runtime = {
            "durable_snapshot": True,
            "summarized_cycles": 1,
            "summary": json.dumps({
                "objective": "完成排版", "constraints": "历史定位信息已过期", "decisions": "重新读取当前块",
                "completed": "已读取旧块", "active_work": "继续修改", "blockers": "无",
                "next_steps": "读取当前文档", "source_refs": "event:1",
            }, ensure_ascii=False),
        }

        _persist_runtime_compaction_snapshot(
            self.db, session_id=self.session.id, assistant_message_id=assistant.id,
            runtime_compaction=runtime, model_id=self.model.id, input_budget_tokens=12_000,
        )
        self.db.commit()
        snapshot = self.db.query(ChatContextSnapshot).one()
        self.assertTrue(snapshot.is_active)
        self.assertEqual(snapshot.compacted_through_event_id, tool_event.id)
        self.assertEqual(snapshot.trigger, "run_automatic")

    def test_incomplete_runtime_source_is_not_promoted(self) -> None:
        _persist_runtime_compaction_snapshot(
            self.db, session_id=self.session.id, assistant_message_id=999,
            runtime_compaction={"durable_snapshot": False, "summarized_cycles": 1, "summary": "{}"},
            model_id=self.model.id, input_budget_tokens=12_000,
        )
        self.assertIsNone(self.db.query(ChatContextSnapshot).first())

    def test_superseded_covered_history_invalidates_memory(self) -> None:
        old_user = self.add_turn("旧偏好", MessageRole.USER)
        old_assistant = self.add_turn("旧结果", MessageRole.ASSISTANT)
        memory = ChatSessionMemory(
            session_id=self.session.id,
            compacted_through_message_id=old_assistant.id,
            summary_json=json.dumps({"user_preferences": ["旧偏好"]}, ensure_ascii=False),
        )
        self.db.add(memory)
        self.db.commit()
        old_user.is_superseded = True
        old_user.superseded_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        self.db.commit()

        stats = self.builder([old_assistant]).snapshot()

        self.assertEqual(stats["state"], "ready")
        self.assertEqual(self.db.query(ChatSessionMemory).one().compacted_through_message_id, 0)

    def test_legacy_lazy_invalidation_recovers_snapshot_after_an_older_branch_change(self) -> None:
        old_user = self.add_turn("已替换的旧请求", MessageRole.USER)
        old_assistant = self.add_turn("已替换的旧结果", MessageRole.ASSISTANT)
        old_user.is_superseded = True
        old_user.superseded_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        checkpoint = ChatContextSnapshot(
            session_id=self.session.id,
            source_start_event_id=0,
            compacted_through_event_id=0,
            compacted_through_message_id=old_assistant.id,
            retained_from_event_id=old_assistant.id + 1,
            summary_json=json.dumps({"objective": "当前任务"}, ensure_ascii=False),
            strategy="agentic",
            trigger="automatic",
            is_active=False,
            invalidation_reason="",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(checkpoint)
        self.db.commit()

        self.builder([]).snapshot()

        self.assertTrue(self.db.get(ChatContextSnapshot, checkpoint.id).is_active)

    def test_smaller_model_reports_compaction_before_mutating_memory(self) -> None:
        self.model.context_window_tokens = 8192
        self.model.context_compaction_threshold_tokens = 7000
        rows: list[ChatMessage] = []
        for index in range(10):
            rows.append(self.add_turn(f"用户任务 {index} " + "内容" * 500, MessageRole.USER))
            rows.append(self.add_turn(f"完成情况 {index} " + "结果" * 500, MessageRole.ASSISTANT))

        stats = self.builder(rows).snapshot()

        self.assertTrue(stats["requires_compaction"])
        self.assertTrue(stats["can_fit_after_compaction"])
        self.assertEqual(stats["state"], "requires_compaction")
        self.assertIsNone(self.db.query(ChatSessionMemory).first())

    def test_memory_is_never_shared_with_another_session(self) -> None:
        other = ChatSession(document_id=1, title="另一个任务")
        self.db.add(other)
        self.db.flush()
        self.db.add(
            ChatSessionMemory(
                session_id=self.session.id,
                compacted_through_message_id=1,
                summary_json=json.dumps({"user_preferences": ["只属于第一会话"]}, ensure_ascii=False),
            )
        )
        other_message = ChatMessage(
            document_id=1,
            session_id=other.id,
            role=MessageRole.USER,
            content="第二会话的独立要求",
        )
        self.db.add(other_message)
        self.db.commit()

        prepared = asyncio.run(
            AgentContextBuilder(
                self.db,
                1,
                other.id,
                self.model,
                HtmlWorkspace("<section><p>正文</p></section>"),
                [other_message],
                "规则",
            ).prepare()
        )

        self.assertNotIn("第一会话", json.dumps(prepared.memory, ensure_ascii=False))
        self.assertEqual([message.content for message in prepared.history], ["第二会话的独立要求"])

    def test_runtime_usage_never_replaces_the_prepared_context_budget(self) -> None:
        prepared = {
            "used_tokens": 12_000,
            "usage_percent": 50,
            "state": "ready",
            "runtime_input_tokens": 0,
        }

        measured = _merge_runtime_context_stats(
            prepared,
            {
                "state": "measured",
                "used_tokens": 4_000,
                "last_turn_output_tokens": 900,
                "cached_input_tokens": 1_200,
            },
        )
        compacted = _merge_runtime_context_stats(
            prepared,
            {
                "state": "in_run_compacted",
                "used_tokens": 5_000,
                "run_original_tokens": 20_000,
                "run_digested_cycles": 4,
                "run_dropped_cycles": 1,
            },
        )
        streaming = _merge_runtime_context_stats(
            prepared,
            {
                "state": "streaming",
                "used_tokens": 5_200,
                "runtime_projected_tokens": 640,
                "runtime_visible_output_tokens": 280,
                "runtime_reasoning_tokens": 220,
                "runtime_tool_argument_tokens": 140,
            },
        )

        self.assertEqual(measured["used_tokens"], 12_000)
        self.assertEqual(measured["state"], "ready")
        self.assertEqual(measured["runtime_input_tokens"], 4_000)
        self.assertEqual(measured["last_model_output_tokens"], 900)
        self.assertEqual(measured["runtime_context_tokens"], 4_000)
        self.assertEqual(measured["runtime_context_source"], "provider_reported")
        self.assertEqual(compacted["used_tokens"], 12_000)
        self.assertEqual(compacted["runtime_original_tokens"], 20_000)
        self.assertEqual(compacted["runtime_digested_cycles"], 4)
        self.assertEqual(streaming["used_tokens"], 12_000)
        self.assertEqual(streaming["runtime_input_tokens"], 5_200)
        self.assertEqual(streaming["runtime_projected_tokens"], 640)
        self.assertEqual(streaming["runtime_tool_argument_tokens"], 140)

        after_tool = _merge_runtime_context_stats(
            prepared,
            {
                "state": "tool_result_context",
                "used_tokens": 5_800,
                "context_source": "server_recomputed_after_tool",
                "context_is_estimate": True,
                "tool_call_id": "call-7",
                "tool_name": "read_blocks",
                "breakdown": {"runtime_system": 1_000, "runtime_history": 2_000, "runtime_tools": 2_800},
            },
        )
        self.assertEqual(after_tool["used_tokens"], 12_000)
        self.assertEqual(after_tool["runtime_context_tokens"], 5_800)
        self.assertEqual(after_tool["runtime_context_breakdown"]["runtime_tools"], 2_800)
        self.assertEqual(after_tool["runtime_context_source"], "server_recomputed_after_tool")
        self.assertEqual(after_tool["runtime_context_tool_call_id"], "call-7")

    def test_runtime_context_stats_rebuild_the_next_turn_message_sequence(self) -> None:
        stats = _runtime_context_stats_for_messages([
            SystemMessage(content="系统规则"),
            HumanMessage(content="请调整标题"),
            AIMessage(content="", tool_calls=[{"id": "call-1", "name": "read_blocks", "args": {"block_ids": ["b1"]}}]),
            ToolMessage(content='{"ok":true,"blocks":["标题"]}', tool_call_id="call-1", name="read_blocks"),
        ])

        self.assertEqual(stats["used_tokens"], sum(stats["breakdown"].values()))
        self.assertGreater(stats["breakdown"]["runtime_system"], 0)
        self.assertGreater(stats["breakdown"]["runtime_history"], 0)
        self.assertGreater(stats["breakdown"]["runtime_tools"], 0)

    def test_manual_compaction_notice_uses_actual_before_and_after_context_sizes(self) -> None:
        content = _context_compaction_notice_content(
            {"compiled_input_tokens": 20_000},
            {"compiled_input_tokens": 5_000, "state": "compacted"},
        )

        self.assertEqual(content, "压缩上下文成功，节省 15,000 tokens，压缩率 75%（20,000 → 5,000 tokens）。")

    def test_preflight_compaction_event_contains_saved_tokens(self) -> None:
        event = _context_compaction_event_data(
            {"compiled_input_tokens": 30_000, "state": "requires_compaction"},
            {"compiled_input_tokens": 8_000, "state": "compacted"},
        )

        self.assertEqual(event["original_tokens"], 30_000)
        self.assertEqual(event["used_tokens"], 8_000)
        self.assertTrue(event["durable_snapshot"])

    def test_manual_compaction_notice_does_not_claim_a_noop_was_compacted(self) -> None:
        content = _context_compaction_notice_content(
            {"used_tokens": 2_000},
            {"used_tokens": 2_000, "state": "ready"},
        )

        self.assertEqual(content, "上下文检查完成，本次无需压缩（当前 2,000 tokens）。")

    def test_manual_compaction_notice_is_not_replayed_to_the_model(self) -> None:
        request = self.add_turn("继续调整正文", MessageRole.USER)
        self.db.add(
            ChatContextEvent(
                document_id=1,
                session_id=self.session.id,
                message_id=request.id,
                ordinal=0,
                kind=ContextEventKind.USER,
                payload_json=json.dumps({"content": request.content}, ensure_ascii=False),
            )
        )
        notice = _persist_context_compaction_notice(
            self.db,
            document_id=1,
            session_id=self.session.id,
            before_stats={"used_tokens": 20_000},
            after_stats={"used_tokens": 5_000, "state": "compacted"},
        )
        self.db.commit()

        prepared = self.builder([request, notice]).snapshot()

        self.assertEqual(notice.role, MessageRole.TOOL)
        self.assertEqual(
            self.db.query(ChatContextEvent).filter(ChatContextEvent.message_id == notice.id).count(),
            0,
        )
        self.assertEqual(prepared["event_count"], 1)

    def test_model_budget_schema_rejects_impossible_window(self) -> None:
        with self.assertRaises(ValidationError):
            ModelCreate(
                model_name="bad-budget",
                display_name="Bad budget",
                context_window_tokens=8192,
                context_compaction_threshold_tokens=7000,
                max_output_tokens=2000,
                tool_result_max_tokens=1000,
            )

    def test_images_add_fixed_context_cost_for_multimodal_model(self) -> None:
        self.model.is_multimodal = True
        user_message = self.add_turn("请参考图片调整版式", MessageRole.USER)
        self.db.add_all([
            ChatImageAttachment(
                id="image-1",
                document_id=1,
                uploader_id=1,
                message_id=user_message.id,
                filename="one.png",
                content_type="image/png",
                size=10,
                storage_mode="local",
                object_key="local/chat-images/image-1.png",
            ),
            ChatImageAttachment(
                id="image-2",
                document_id=1,
                uploader_id=1,
                message_id=user_message.id,
                filename="two.png",
                content_type="image/png",
                size=10,
                storage_mode="local",
                object_key="local/chat-images/image-2.png",
            ),
        ])
        self.db.flush()

        stats = AgentContextBuilder(
            self.db,
            1,
            self.session.id,
            self.model,
            HtmlWorkspace("<section><p>正文</p></section>"),
            [user_message],
            "规则",
            current_image_count=2,
        ).snapshot()

        self.assertEqual(stats["breakdown"]["image_inputs"], 2048)
        self.assertGreaterEqual(stats["breakdown"]["recent_history"], 2048)

    def test_non_multimodal_context_omits_image_blocks_and_keeps_notice(self) -> None:
        user_message = self.add_turn("请继续调整", MessageRole.USER)
        self.db.add(
            ChatImageAttachment(
                id="image-3",
                document_id=1,
                uploader_id=1,
                message_id=user_message.id,
                filename="three.png",
                content_type="image/png",
                size=10,
                storage_mode="local",
                object_key="local/chat-images/image-3.png",
            )
        )
        self.db.flush()

        prepared = asyncio.run(self.builder([user_message]).prepare())

        self.assertIsInstance(prepared.history[0].content, str)
        self.assertIn("当前模型不支持读取图片", prepared.history[0].content)
        self.assertEqual(prepared.stats["breakdown"]["image_inputs"], 0)

    def test_multimodal_history_rebuilds_image_blocks(self) -> None:
        self.model.is_multimodal = True
        user_message = self.add_turn("请参考图片", MessageRole.USER)
        self.db.add(
            ChatImageAttachment(
                id="image-4",
                document_id=1,
                uploader_id=1,
                message_id=user_message.id,
                filename="four.png",
                content_type="image/png",
                size=10,
                storage_mode="local",
                object_key="local/chat-images/image-4.png",
            )
        )
        self.db.flush()

        with patch("app.services.agent_context.image_content_blocks", return_value=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]):
            prepared = asyncio.run(self.builder([user_message]).prepare())

        self.assertEqual(prepared.history[0].content[0], {"type": "text", "text": "请参考图片"})
        self.assertEqual(prepared.history[0].content[1]["type"], "image_url")


if __name__ == "__main__":
    unittest.main()
