"""Session-history retrieval must not escape the active context boundary."""
from __future__ import annotations

import unittest
import json
from datetime import datetime, timezone

import app.models  # noqa: F401 - register all metadata tables.
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_history_archive import ChatHistoryArchive
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.chat_tool_output import ChatToolOutput
from app.services.session_history import SessionHistoryError, SessionHistoryReader


class SessionHistoryReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.session = ChatSession(document_id=1, title="当前会话")
        self.other_session = ChatSession(document_id=1, title="其他会话")
        self.db.add_all([self.session, self.other_session])
        self.db.flush()
        self.old_message = ChatMessage(document_id=1, session_id=self.session.id, role=MessageRole.USER, content="old secret")
        self.current_message = ChatMessage(document_id=1, session_id=self.session.id, role=MessageRole.USER, content="current keyword")
        self.other_message = ChatMessage(document_id=1, session_id=self.other_session.id, role=MessageRole.USER, content="current keyword other")
        self.db.add_all([self.old_message, self.current_message, self.other_message])
        self.db.flush()
        old_event = ChatContextEvent(
                document_id=1, session_id=self.session.id, message_id=self.old_message.id,
                ordinal=0, kind=ContextEventKind.USER, payload_json='{"content":"old secret"}',
            )
        current_event = ChatContextEvent(
                document_id=1, session_id=self.session.id, message_id=self.current_message.id,
                ordinal=0, kind=ContextEventKind.USER, payload_json='{"content":"current keyword"}',
            )
        self.db.add_all([
            old_event,
            current_event,
            ChatContextEvent(
                document_id=1, session_id=self.other_session.id, message_id=self.other_message.id,
                ordinal=0, kind=ContextEventKind.USER, payload_json='{"content":"current keyword other"}',
            ),
        ])
        self.db.flush()
        self.old_event_id = old_event.id
        self.current_event_id = current_event.id
        self.old_run = AgentRun(
            id="run-old", document_id=1, session_id=self.session.id, user_id=1,
            user_message_id=self.old_message.id, client_request_id="request-old", status=AgentRunStatus.COMPLETED,
        )
        self.current_run = AgentRun(
            id="run-current", document_id=1, session_id=self.session.id, user_id=1,
            user_message_id=self.current_message.id, client_request_id="request-current", status=AgentRunStatus.COMPLETED,
        )
        self.db.add_all([self.old_run, self.current_run])
        self.db.flush()
        self.db.add_all([
            ChatToolOutput(
                output_id="tool-old", document_id=1, session_id=self.session.id, run_id=self.old_run.id,
                tool_call_id="call-old", tool_name="read_blocks", content="old secret tool", content_bytes=15,
                content_lines=1, estimated_tokens=4, checksum="a" * 64, retention_mode="session",
                expires_at=datetime.now(timezone.utc),
            ),
            ChatToolOutput(
                output_id="tool-current", document_id=1, session_id=self.session.id, run_id=self.current_run.id,
                tool_call_id="call-current", tool_name="read_blocks", content="current keyword tool", content_bytes=20,
                content_lines=1, estimated_tokens=5, checksum="b" * 64, retention_mode="session",
                expires_at=datetime.now(timezone.utc),
            ),
        ])
        self.db.commit()
        self.reader = SessionHistoryReader(1, self.session.id)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_search_is_scoped_to_one_session(self) -> None:
        results = self.reader.search(self.db, "current keyword")
        refs = {item["reference"] for item in results["results"]}
        self.assertIn("tool:tool-current", refs)
        self.assertEqual(refs, {f"event:{self.current_event_id}", "tool:tool-current"})

    def test_event_and_tool_pages_reconstruct_exact_original_text(self) -> None:
        content = ("中文分页 alpha\n" * 500) + "  literal … ending \n  "
        event = self.db.get(ChatContextEvent, self.current_event_id)
        output = self.db.get(ChatToolOutput, "tool-current")
        assert event is not None and output is not None
        event.payload_json = json.dumps({"content": content}, ensure_ascii=False)
        output.content = content
        self.db.commit()
        for reference in (f"event:{event.id}", "tool:tool-current"):
            with self.subTest(reference=reference):
                pages = []
                cursor = 0
                for _ in range(100):
                    page = self.reader.read(self.db, reference, cursor=cursor, max_tokens=128)
                    pages.append(page["content"])
                    if page["next_cursor"] is None:
                        self.assertFalse(page["truncated"])
                        break
                    self.assertTrue(page["truncated"])
                    self.assertEqual(page["next_cursor"], cursor + len(page["content"]))
                    self.assertGreater(page["next_cursor"], cursor)
                    cursor = page["next_cursor"]
                else:
                    self.fail("Pagination never reached the end")
                self.assertGreater(len(pages), 1)
                self.assertEqual("".join(pages), content)
                self.assertEqual(self.reader.read(self.db, reference, cursor=len(content) + 10)["content"], "")

    def test_historical_images_follow_canonical_selection_order(self) -> None:
        self.db.add_all([
            ChatImageAttachment(
                id=image_id, document_id=1, uploader_id=1, message_id=self.current_message.id,
                filename=f"{image_id}.png", content_type="image/png", size=10,
                storage_mode="local", object_key=f"{image_id}.png",
            ) for image_id in ("image-a", "image-b", "image-c")
        ])
        event = self.db.get(ChatContextEvent, self.current_event_id)
        assert event is not None
        event.payload_json = json.dumps({"content": "current keyword", "image_attachment_ids": ["image-c", "image-a", "image-b"]})
        self.db.commit()

        detail = self.reader.read(self.db, f"event:{event.id}")
        search = self.reader.search(self.db, "current keyword")
        hit = next(item for item in search["results"] if item["kind"] == "user")
        self.assertEqual([image["attachment_id"] for image in detail["images"]], ["image-c", "image-a", "image-b"])
        self.assertEqual(hit["images"], detail["images"])

    def test_image_references_survive_history_retrieval_within_active_boundary(self) -> None:
        self.db.add_all([
            ChatImageAttachment(
                id="current-image", document_id=1, uploader_id=1,
                message_id=self.current_message.id, filename="layout.png",
                content_type="image/png", size=10, storage_mode="local", object_key="current.png",
            ),
            ChatImageAttachment(
                id="old-image", document_id=1, uploader_id=1,
                message_id=self.old_message.id, filename="old.png",
                content_type="image/png", size=10, storage_mode="local", object_key="old.png",
            ),
        ])
        self.session.context_start_message_id = self.old_message.id
        self.db.commit()

        result = self.reader.search(self.db, "current keyword")
        user_hit = next(item for item in result["results"] if item["kind"] == "user")
        self.assertEqual(user_hit["images"], [{"attachment_id": "current-image", "filename": "layout.png", "url": "/api/documents/1/chat-images/current-image/content"}])
        detail = self.reader.read(self.db, f"event:{self.current_event_id}")
        self.assertEqual(detail["images"], user_hit["images"])
        with self.assertRaises(SessionHistoryError):
            self.reader.read(self.db, f"event:{self.old_event_id}")

    def test_context_truncation_hides_old_events_and_tool_outputs(self) -> None:
        self.session.context_start_message_id = self.old_message.id
        self.db.commit()

        self.assertEqual(self.reader.search(self.db, "old secret")["total"], 0)
        with self.assertRaisesRegex(SessionHistoryError, "截断"):
            self.reader.read(self.db, f"event:{self.old_event_id}")
        with self.assertRaisesRegex(SessionHistoryError, "截断"):
            self.reader.read(self.db, "tool:tool-old")
        self.assertEqual(self.reader.read(self.db, "tool:tool-current")["reference"], "tool:tool-current")

    def test_reask_archive_hides_events_and_tool_output_but_keeps_the_raw_rows(self) -> None:
        archive = ChatHistoryArchive(
            session_id=self.session.id,
            source_message_id=self.current_message.id,
            reason="reask",
        )
        self.db.add(archive)
        self.db.flush()
        self.current_message.is_superseded = True
        self.current_message.history_archive_id = archive.id
        self.db.commit()

        self.assertEqual(self.reader.search(self.db, "current keyword")["total"], 0)
        with self.assertRaisesRegex(SessionHistoryError, "不存在"):
            self.reader.read(self.db, f"event:{self.current_event_id}")
        with self.assertRaisesRegex(SessionHistoryError, "已放弃"):
            self.reader.read(self.db, "tool:tool-current")
        self.assertEqual(self.db.query(ChatContextEvent).filter_by(id=self.current_event_id).count(), 1)
        self.assertEqual(self.db.query(ChatToolOutput).filter_by(output_id="tool-current").count(), 1)


if __name__ == "__main__":
    unittest.main()
