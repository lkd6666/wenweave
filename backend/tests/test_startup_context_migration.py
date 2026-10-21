import json
import unittest
from unittest.mock import patch

import app.models  # noqa: F401
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import bootstrap
from app.db.base import Base
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession, ChatSessionMemory
from app.models.document import Document
from app.models.user import User


class StartupContextMigrationTests(unittest.TestCase):
    def test_attachment_delivery_migration_preserves_sources_and_is_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="image-migration", password_hash="unused")
            db.add(user)
            db.flush()
            document = Document(owner_id=user.id, title="Migration", current_html="<p>正文</p>")
            db.add(document)
            db.flush()
            for attachment_id, mode, key in (
                ("pasted", "local", "local/chat-images/pasted.png"),
                ("cloud-pasted", "oss", "yibanpaiban/chat-images/pasted.png"),
                ("gallery", "local", "local/images/library.png"),
            ):
                db.add(ChatImageAttachment(id=attachment_id, document_id=document.id, uploader_id=user.id,
                                           filename="photo.png", content_type="image/png", size=10,
                                           storage_mode=mode, object_key=key))
            db.commit()
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE chat_image_attachments DROP COLUMN is_direct_input"))
        with patch.object(bootstrap, "engine", engine):
            bootstrap.migrate_schema()
            with engine.begin() as connection:
                flags = dict(connection.execute(text("SELECT id, is_direct_input FROM chat_image_attachments")).all())
                self.assertEqual(flags, {"pasted": 1, "cloud-pasted": 1, "gallery": 0})
                connection.execute(text("UPDATE chat_image_attachments SET is_direct_input = 0 WHERE id = 'pasted'"))
            bootstrap.migrate_schema()
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT is_direct_input FROM chat_image_attachments WHERE id = 'pasted'")).scalar(), 0)

    def test_backfill_preserves_existing_events_and_memory_and_only_adds_missing_messages(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="migration", password_hash="unused")
            db.add(user)
            db.flush()
            document = Document(owner_id=user.id, title="Migration", current_html="<p>正文</p>")
            db.add(document)
            db.flush()
            pending = ChatSession(document_id=document.id)
            migrated = ChatSession(document_id=document.id)
            db.add_all([pending, migrated])
            db.flush()
            request = ChatMessage(document_id=document.id, session_id=pending.id, role=MessageRole.USER, content="读取正文")
            response = ChatMessage(
                document_id=document.id, session_id=pending.id, role=MessageRole.ASSISTANT, content="已读取",
                tool_calls_json=json.dumps([{
                    "id": "call-1", "name": "read_blocks", "arguments": {"limit": 1},
                    "result": '{"revision":"v1","blocks":[]}', "status": "success",
                }]),
            )
            existing = ChatMessage(document_id=document.id, session_id=migrated.id, role=MessageRole.ASSISTANT, content="display only")
            empty = ChatMessage(document_id=document.id, session_id=pending.id, role=MessageRole.ASSISTANT, content="")
            db.add_all([request, response, existing, empty])
            db.flush()
            canonical = ChatContextEvent(
                document_id=document.id, session_id=migrated.id, message_id=existing.id,
                ordinal=0, kind=ContextEventKind.ASSISTANT, payload_json='{"content":"canonical"}',
            )
            unbound = ChatContextEvent(
                document_id=document.id, session_id=pending.id, message_id=None,
                ordinal=0, kind=ContextEventKind.USER, payload_json='{"content":"unbound"}',
            )
            db.add_all([canonical, unbound])
            db.flush()
            db.add_all([
                ChatSessionMemory(session_id=pending.id, compacted_through_message_id=response.id),
                ChatSessionMemory(
                    session_id=migrated.id, compacted_through_message_id=existing.id,
                    compacted_through_event_id=canonical.id, summary_json='{"summary":"retained"}',
                ),
            ])
            db.commit()
            document_id, pending_id, migrated_id = document.id, pending.id, migrated.id
            request_id, response_id, canonical_id = request.id, response.id, canonical.id

        def snapshot():
            with engine.connect() as connection:
                return (
                    connection.execute(select(ChatContextEvent.__table__).order_by(ChatContextEvent.id)).all(),
                    connection.execute(select(ChatSessionMemory.__table__).order_by(ChatSessionMemory.id)).all(),
                )

        with patch.object(bootstrap, "engine", engine):
            bootstrap.migrate_schema()
            with Session(engine) as db:
                events = db.scalars(select(ChatContextEvent).where(
                    ChatContextEvent.message_id.in_([request_id, response_id])
                ).order_by(ChatContextEvent.id)).all()
                self.assertEqual([event.kind for event in events], [
                    ContextEventKind.USER, ContextEventKind.ASSISTANT,
                    ContextEventKind.TOOL, ContextEventKind.ASSISTANT,
                ])
                self.assertEqual([event.ordinal for event in events], [0, 0, 1, 2])
                self.assertEqual(events[0].payload, {"content": "读取正文"})
                self.assertEqual(events[1].payload["tool_calls"][0]["args"], {"limit": 1})
                self.assertEqual(events[2].payload["content"], '{"revision":"v1","blocks":[]}')
                self.assertEqual(events[2].document_revision, "v1")
                self.assertEqual(events[3].payload, {"content": "已读取"})
                self.assertTrue(all(event.is_legacy for event in events))
                self.assertEqual(db.get(ChatContextEvent, canonical_id).payload, {"content": "canonical"})
                memories = {memory.session_id: memory for memory in db.scalars(select(ChatSessionMemory))}
                self.assertEqual(memories[pending_id].compacted_through_event_id, events[-1].id)
                self.assertEqual(memories[migrated_id].compacted_through_event_id, canonical_id)
                self.assertEqual(memories[migrated_id].summary_json, '{"summary":"retained"}')

            first = snapshot()
            bootstrap.migrate_schema()
            self.assertEqual(snapshot(), first)

            with Session(engine) as db:
                late = ChatMessage(document_id=document_id, session_id=pending_id, role=MessageRole.USER, content="继续")
                db.add(late)
                db.commit()
                late_id = late.id
            bootstrap.migrate_schema()
            with Session(engine) as db:
                late_events = db.scalars(select(ChatContextEvent).where(ChatContextEvent.message_id == late_id)).all()
                self.assertEqual(len(late_events), 1)
                self.assertEqual(late_events[0].payload, {"content": "继续"})
            self.assertEqual(snapshot()[1], first[1])
