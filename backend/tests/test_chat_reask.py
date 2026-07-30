"""Regression coverage for Cline-style anchored historical re-asks."""
from __future__ import annotations

import json
import unittest

import app.models  # noqa: F401 - registers every table before create_all.
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_history_archive import ChatHistoryArchive
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.user import User, UserRole
from app.services.agent_context import AgentContextBuilder, ContextRecord, context_prefix_hash
from app.services.chat_reask import ChatReaskConflictError, ChatReaskError, activate_reask
from app.services.document_versions import content_checksum
from app.services.html_workspace import HtmlWorkspace


class ChatReaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            username="reask-user",
            display_name="重问用户",
            password_hash="not-used",
            role=UserRole.ADMIN,
        )
        self.model = AIModel(
            provider_id=1,
            model_name="test-model",
            display_name="Test",
            context_window_tokens=32_768,
            context_compaction_threshold_tokens=16_000,
            max_output_tokens=1_000,
            tool_result_max_tokens=1_000,
        )
        self.db.add_all([self.user, self.model])
        self.db.flush()
        self.document = Document(owner_id=self.user.id, title="测试稿", current_html="<p>第二版</p>")
        self.db.add(self.document)
        self.db.flush()
        self.session = ChatSession(document_id=self.document.id, title="上下文测试")
        self.other_session = ChatSession(document_id=self.document.id, title="其他会话")
        self.db.add_all([self.session, self.other_session])
        self.db.flush()

        self.first_user = self._message(MessageRole.USER, "先把标题改为蓝色", "<p>初稿</p>")
        self.first_assistant = self._message(
            MessageRole.ASSISTANT, "标题已经改为蓝色", "<p>初稿</p>", "<p>第一版</p>"
        )
        self.second_user = self._message(MessageRole.USER, "再增加副标题", "<p>第一版</p>")
        self.second_assistant = self._message(
            MessageRole.ASSISTANT, "副标题已经添加", "<p>第一版</p>", "<p>第二版</p>"
        )
        self.events = [
            self._event(self.first_user, ContextEventKind.USER, {"content": self.first_user.content}),
            self._event(self.first_assistant, ContextEventKind.ASSISTANT, {"content": self.first_assistant.content}),
            self._event(self.second_user, ContextEventKind.USER, {"content": self.second_user.content}),
            self._event(self.second_assistant, ContextEventKind.ASSISTANT, {"content": self.second_assistant.content}),
        ]
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _message(
        self, role: MessageRole, content: str, html_before: str, html_after: str | None = None
    ) -> ChatMessage:
        row = ChatMessage(
            document_id=self.document.id,
            session_id=self.session.id,
            role=role,
            content=content,
            html_before=html_before,
            html_after=html_after,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _event(self, message: ChatMessage, kind: ContextEventKind, payload: dict) -> ChatContextEvent:
        row = ChatContextEvent(
            document_id=self.document.id,
            session_id=self.session.id,
            message_id=message.id,
            ordinal=0,
            kind=kind,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _snapshot(self, count: int) -> ChatContextSnapshot:
        records = [
            ContextRecord(
                id=event.id,
                message_id=event.message_id,
                kind=event.kind.value,
                payload=event.payload,
                document_revision=event.document_revision,
                is_legacy=event.is_legacy,
            )
            for event in self.events
        ]
        boundary = self.events[count - 1]
        summary = {
            "objective": "延续已经确认的排版目标",
            "important_details": ["标题采用蓝色"],
            "user_preferences": [],
            "completed_intents": ["标题已改为蓝色"],
            "active_work": [],
            "pending_tasks": [],
            "blocked": [],
            "next_move": [],
            "relevant_files": [],
            "source_refs": [],
            "narrative": "旧前缀摘要",
        }
        snapshot = ChatContextSnapshot(
            session_id=self.session.id,
            source_start_event_id=self.events[0].id,
            compacted_through_event_id=boundary.id,
            compacted_through_message_id=boundary.message_id or 0,
            retained_from_event_id=boundary.id + 1,
            summary_json=json.dumps(summary, ensure_ascii=False),
            strategy="agentic",
            trigger="test",
            model_id=self.model.id,
            input_budget_tokens=self.model.context_compaction_threshold_tokens,
            source_event_count=count,
            source_prefix_hash=context_prefix_hash(records, count),
            context_generation=self.session.context_generation,
            is_active=True,
        )
        self.db.add(snapshot)
        self.db.commit()
        return snapshot

    def _builder(self) -> AgentContextBuilder:
        visible_messages = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == self.session.id, ChatMessage.is_superseded.is_(False))
            .order_by(ChatMessage.id)
            .all()
        )
        return AgentContextBuilder(
            self.db,
            self.document.id,
            self.session.id,
            self.model,
            HtmlWorkspace(self.document.current_html),
            visible_messages,
            "系统规则",
        )

    def test_reask_after_snapshot_reuses_unchanged_prefix(self) -> None:
        snapshot = self._snapshot(2)

        activation = activate_reask(
            self.db,
            document=self.document,
            session=self.session,
            source_message_id=self.second_user.id,
        )
        self.db.commit()

        self.assertEqual(activation.current_html, "<p>第一版</p>")
        self.assertEqual(self.document.current_html, "<p>第一版</p>")
        self.assertFalse(self.first_user.is_superseded)
        self.assertFalse(self.first_assistant.is_superseded)
        self.assertTrue(self.second_user.is_superseded)
        self.assertTrue(self.second_assistant.is_superseded)
        self.assertEqual(self.db.query(ChatHistoryArchive).count(), 1)

        stats = self._builder().snapshot()
        self.assertTrue(self.db.get(ChatContextSnapshot, snapshot.id).is_active)
        self.assertTrue(stats["snapshot_prefix_valid"])
        self.assertEqual(stats["snapshot_source_event_count"], 2)
        self.assertEqual(stats["hot_event_count"], 0)

    def test_reask_inside_snapshot_invalidates_summary_and_keeps_raw_archive(self) -> None:
        snapshot = self._snapshot(4)

        activate_reask(
            self.db,
            document=self.document,
            session=self.session,
            source_message_id=self.second_user.id,
        )
        self.db.commit()

        self.assertFalse(self.db.get(ChatContextSnapshot, snapshot.id).is_active)
        stats = self._builder().snapshot()
        self.assertFalse(stats["snapshot_prefix_valid"])
        self.assertEqual(stats["hot_event_count"], 2)
        self.assertEqual(self.db.query(ChatContextEvent).count(), 4)

    def test_prefix_hash_invalidates_even_when_legacy_message_boundary_lags(self) -> None:
        snapshot = self._snapshot(4)
        # Older snapshots only had a message cutoff. Simulate a stale cutoff
        # that does not reveal the later event coverage; source_count + hash
        # must still prevent a retired suffix from being summarized into the
        # new request.
        snapshot.compacted_through_message_id = self.first_assistant.id
        self.db.commit()

        activate_reask(
            self.db,
            document=self.document,
            session=self.session,
            source_message_id=self.second_user.id,
        )
        self.assertTrue(self.db.get(ChatContextSnapshot, snapshot.id).is_active)

        stats = self._builder().snapshot()
        self.assertFalse(self.db.get(ChatContextSnapshot, snapshot.id).is_active)
        self.assertFalse(stats["snapshot_prefix_valid"])

    def test_cross_session_target_and_document_conflict_leave_no_archive(self) -> None:
        other_message = ChatMessage(
            document_id=self.document.id,
            session_id=self.other_session.id,
            role=MessageRole.USER,
            content="其他会话请求",
            html_before="<p>第二版</p>",
        )
        self.db.add(other_message)
        self.db.commit()

        with self.assertRaisesRegex(ChatReaskError, "当前对话"):
            activate_reask(
                self.db,
                document=self.document,
                session=self.session,
                source_message_id=other_message.id,
            )
        self.assertEqual(self.db.query(ChatHistoryArchive).count(), 0)
        self.assertEqual(self.document.current_html, "<p>第二版</p>")

        self.document.current_html = "<p>手动修改</p>"
        with self.assertRaisesRegex(ChatReaskError, "手动或其他对话修改"):
            activate_reask(
                self.db,
                document=self.document,
                session=self.session,
                source_message_id=self.second_user.id,
            )
        self.assertEqual(self.db.query(ChatHistoryArchive).count(), 0)
        self.assertFalse(self.second_user.is_superseded)

    def test_confirmed_conflict_discards_current_document_changes(self) -> None:
        self.document.current_html = "<p>手动修改</p>"
        checksum = content_checksum(self.document.current_html)

        activation = activate_reask(
            self.db,
            document=self.document,
            session=self.session,
            source_message_id=self.second_user.id,
            discard_document_changes=True,
            expected_current_checksum=checksum,
        )
        self.db.commit()

        self.assertEqual(activation.current_html, "<p>第一版</p>")
        self.assertEqual(self.document.current_html, "<p>第一版</p>")
        self.assertEqual(self.db.query(ChatHistoryArchive).count(), 1)
        self.assertTrue(self.second_user.is_superseded)

    def test_confirmed_conflict_rejects_stale_checksum_without_mutation(self) -> None:
        self.document.current_html = "<p>手动修改</p>"
        stale_checksum = content_checksum(self.document.current_html)
        self.document.current_html = "<p>更新后的手动修改</p>"

        with self.assertRaises(ChatReaskConflictError) as raised:
            activate_reask(
                self.db,
                document=self.document,
                session=self.session,
                source_message_id=self.second_user.id,
                discard_document_changes=True,
                expected_current_checksum=stale_checksum,
            )

        self.assertEqual(raised.exception.current_checksum, content_checksum("<p>更新后的手动修改</p>"))
        self.assertEqual(self.db.query(ChatHistoryArchive).count(), 0)
        self.assertEqual(self.document.current_html, "<p>更新后的手动修改</p>")
        self.assertFalse(self.second_user.is_superseded)


if __name__ == "__main__":
    unittest.main()
