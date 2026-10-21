import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app import bootstrap
from app.api.routes.chat import _context_compaction_event_data, _merge_runtime_context_stats
from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.template_library import TemplateLibraryItem, TemplateSourceType
from app.models.user import User, UserRole
from app.schemas.chat import ChatContextPreviewRequest, ChatSendRequest
from app.api.routes import chat as chat_routes
from app.services.agent_context import AgentContextBuilder
from app.services.agent_run_recovery import recover_interrupted_turn
from app.services.chat_images import delete_attachment_object, duplicate_attachment
from app.services.chat_session_context import replace_session_attached_templates, session_attached_templates
from app.services.context_recovery import persist_recovered_context
from app.services.html_workspace import HtmlWorkspace


class ContextContinuationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.session = ChatSession(document_id=1, title="恢复测试")
        self.model = AIModel(provider_id=1, model_name="test", display_name="test",
                             context_window_tokens=64_000, context_compaction_threshold_tokens=50_000,
                             max_output_tokens=2_000, tool_result_max_tokens=4_000)
        self.db.add_all([self.session, self.model])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_restart_then_continue_preserves_edits_images_and_next_step(self):
        def event(name, data):
            return SimpleNamespace(event=name, payload_json=json.dumps(data, ensure_ascii=False))

        results = [
            ("edit", "apply_html_patch", {"revision": "obsolete", "ok": True, "summary": "标题已改成中秋快乐", "block_id": "stale-block"}),
            ("image", "generate_article_images", {"id": "generation-1", "assets": [{"id": "asset-1", "url": "https://images.example/moon.png"}]}),
            ("view", "view_article_images", {"images": [{"attachment_id": "reference-1", "label": "已读取的月亮参考图"}]}),
        ]
        events = [event("reasoning_delta", {"text": "PRIVATE_REASONING"})]
        for call_id, name, result in results:
            events.extend([
                event("tool_call", {"id": call_id, "name": name, "arguments": {}}),
                event("tool_result", {"id": call_id, "name": name, "result": "已完成", "model_input": {"state": "available", "content": json.dumps(result, ensure_ascii=False)}}),
            ])
        events.append(event("text_delta", {"text": "已完成标题，下一步把月亮候选放入正文。"}))
        recovered = recover_interrupted_turn(events, "服务重启，本轮未完成。")
        message = ChatMessage(document_id=1, session_id=self.session.id, role=MessageRole.ASSISTANT,
                              content=recovered.content, tool_calls_json=json.dumps(recovered.tool_calls, ensure_ascii=False),
                              turn_blocks_json=json.dumps(recovered.turn_blocks, ensure_ascii=False))
        self.db.add(message)
        self.db.flush()
        # Recovery can happen after a later user message already exists.
        continuation = ChatMessage(document_id=1, session_id=self.session.id, role=MessageRole.USER, content="继续")
        self.db.add(continuation)
        self.db.flush()
        self.db.add(ChatContextEvent(document_id=1, session_id=self.session.id, message_id=continuation.id,
                                    ordinal=0, kind=ContextEventKind.USER, payload_json='{"content":"继续"}'))
        self.db.flush()
        self.assertTrue(persist_recovered_context(self.db, message, "run-1"))
        self.db.flush()
        self.assertFalse(persist_recovered_context(self.db, message, "run-1"))
        builder = AgentContextBuilder(self.db, 1, self.session.id, self.model,
                                      HtmlWorkspace("<p>中秋快乐</p>"), [message, continuation], "系统规则")
        history = asyncio.run(builder.prepare()).history
        rendered = "\n".join(str(item.content) for item in history)
        self.assertIn("标题已改成中秋快乐", rendered)
        self.assertIn("https://images.example/moon.png", rendered)
        self.assertIn("reference-1", rendered)
        self.assertIn("下一步", rendered)
        self.assertNotIn("PRIVATE_REASONING", rendered)
        self.assertNotIn("stale-block", rendered)
        self.assertEqual(history[-1].content, "继续")

    def test_budget_includes_schema_and_stream_growth_but_not_private_reasoning(self):
        prepared = {"used_tokens": 10_000, "active_context_threshold_tokens": 20_000}
        measured = _merge_runtime_context_stats(prepared, {"state": "measured", "used_tokens": 9_000})
        after_tool = _merge_runtime_context_stats(measured, {
            "state": "tool_result_context", "used_tokens": 16_000, "tool_schema_tokens": 4_000,
            "input_budget_tokens": 20_000, "breakdown": {"runtime_tools": 16_000},
        })
        self.assertEqual(after_tool["used_tokens"], 20_000)
        self.assertEqual(after_tool["usage_percent"], 100)
        self.assertEqual(after_tool["runtime_input_tokens"], 9_000)
        self.assertEqual(sum(after_tool["runtime_context_breakdown"].values()), 20_000)
        streamed = _merge_runtime_context_stats(after_tool, {
            "state": "streaming", "used_tokens": 5_000, "tool_schema_tokens": 4_000,
            "runtime_visible_output_tokens": 100, "runtime_tool_argument_tokens": 200,
            "runtime_reasoning_tokens": 5_000, "token_estimate_multiplier": 1.6,
        })
        self.assertEqual(streamed["used_tokens"], 9_480)

    def test_model_switch_compaction_details_contain_real_memory(self):
        memory = {"objective": "完成中秋排版", "completed_intents": ["已生成月亮"], "next_move": ["应用候选图"]}
        detail = _context_compaction_event_data({"used_tokens": 30_000}, {"used_tokens": 8_000, "state": "compacted"}, memory)
        self.assertEqual(json.loads(detail["summary"]), memory)
        self.assertGreater(detail["summary_tokens"], 0)

    def test_deleting_a_reused_draft_preserves_the_original_image(self):
        source = ChatImageAttachment(id="source", document_id=1, uploader_id=1, message_id=1,
                                     filename="moon.png", content_type="image/png", size=10,
                                     storage_mode="local", object_key="chat-images/moon.png")
        self.db.add(source)
        self.db.flush()
        duplicate = duplicate_attachment(self.db, source=source, uploader_id=1)
        self.db.flush()
        with patch("app.services.chat_images.local_uploads.delete") as delete:
            delete_attachment_object(self.db, duplicate)
            self.db.delete(duplicate)
            self.db.flush()
            delete.assert_not_called()
            delete_attachment_object(self.db, source)
            delete.assert_called_once_with(source.object_key)

    def test_existing_image_schema_migrates_without_copying_or_losing_references(self):
        self.db.close()
        with self.engine.begin() as connection:
            connection.execute(text("CREATE UNIQUE INDEX old_image_object_key ON chat_image_attachments (object_key)"))
        # SQLite inline UNIQUE is what the deployed old model used.
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE chat_image_attachments"))
            connection.execute(text("CREATE TABLE chat_image_attachments (id VARCHAR(36) PRIMARY KEY, document_id INTEGER NOT NULL, uploader_id INTEGER NOT NULL, message_id INTEGER, filename TEXT NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL, storage_mode TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
            connection.execute(text("INSERT INTO chat_image_attachments (id,document_id,uploader_id,filename,content_type,size,storage_mode,object_key) VALUES ('source',1,1,'moon.png','image/png',10,'local','moon.png')"))
        with patch.object(bootstrap, "engine", self.engine):
            bootstrap.migrate_schema()
            bootstrap.migrate_schema()
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT object_key FROM chat_image_attachments")).scalar(), "moon.png")
            self.assertFalse(inspect(connection).get_unique_constraints("chat_image_attachments"))

    def test_historical_image_preview_and_resend_do_not_upload_or_move_original(self):
        user = User(id=1, username="image-reask", display_name="图片测试", password_hash="unused", role=UserRole.ADMIN)
        document = Document(id=1, owner_id=1, title="中秋", current_html="<p>中秋</p>")
        provider = AIProvider(id=1, name="测试", provider_type=ProviderType.OPENAI_COMPATIBLE, base_url="https://example.invalid")
        self.db.add_all([user, document, provider])
        self.model.provider = provider
        self.model.is_multimodal = True
        original = ChatMessage(document_id=1, session_id=self.session.id, role=MessageRole.USER,
                               content="使用这张图", html_before=document.current_html)
        self.db.add(original)
        self.db.flush()
        source = ChatImageAttachment(id="source-image", document_id=1, uploader_id=1, message_id=original.id,
                                     filename="moon.png", content_type="image/png", size=10,
                                     storage_mode="oss", object_key="moon.png")
        self.db.add(source)
        self.db.commit()

        async def resend():
            result = await chat_routes.start_chat_run(1, ChatSendRequest(
                model_id=self.model.id, session_id=self.session.id, message="重新调整",
                client_request_id="reuse-image-request", reask_from_message_id=original.id,
                image_attachment_ids=[source.id],
            ), user, self.db)
            await asyncio.sleep(0)
            return result

        with (
            patch.object(chat_routes, "build_chat_model", return_value=(None, None)),
            patch.object(chat_routes, "build_compaction_model", return_value=None),
            patch.object(chat_routes, "_execute_agent_run", new_callable=AsyncMock) as execute,
            patch.object(chat_routes, "agent_run_manager", lease_seconds=120, worker_id="image-test-worker"),
            patch.object(chat_routes, "_require_agent_capacity"),
            patch("app.services.chat_images.read_attachment_bytes") as read,
            patch("app.services.chat_images.oss_client.put_object_bytes") as upload,
        ):
            chat_routes.preview_chat_context(1, ChatContextPreviewRequest(
                model_id=self.model.id, session_id=self.session.id, message="重新调整", image_attachment_ids=[source.id],
            ), user, self.db)
            self.assertEqual(self.db.query(ChatImageAttachment).count(), 1)
            result = asyncio.run(resend())
            read.assert_not_called()
            upload.assert_not_called()
        self.db.refresh(source)
        self.assertEqual(source.message_id, original.id)
        copied = self.db.query(ChatImageAttachment).filter(ChatImageAttachment.message_id == result.user_message_id).one()
        self.assertNotEqual(copied.id, source.id)
        self.assertEqual(copied.object_key, source.object_key)
        self.assertEqual(execute.call_args.kwargs["image_attachment_ids"], [copied.id])

    def test_queued_template_snapshot_does_not_replace_the_next_draft_resources(self):
        user = User(id=1, username="template-test", password_hash="unused", role=UserRole.ADMIN)
        document = Document(id=1, owner_id=1, title="Templates", current_html="<p>Article</p>")
        provider = AIProvider(id=1, name="Test", provider_type=ProviderType.OPENAI_COMPATIBLE, base_url="https://example.invalid")
        first = TemplateLibraryItem(name="First", html="<p>First</p>", source_type=TemplateSourceType.SOURCE)
        second = TemplateLibraryItem(name="Second", html="<p>Second</p>", source_type=TemplateSourceType.SOURCE)
        self.db.add_all([user, document, provider, first, second])
        self.model.provider = provider
        self.db.flush()
        replace_session_attached_templates(self.db, self.session.id, [second.id])
        self.db.commit()

        async def start():
            result = await chat_routes.start_chat_run(1, ChatSendRequest(
                model_id=self.model.id, session_id=self.session.id, message="Use @component1",
                client_request_id="queued-template-request", template_ids=[first.id],
            ), user, self.db)
            await asyncio.sleep(0)
            return result

        with (
            patch.object(chat_routes, "build_chat_model", return_value=(None, None)),
            patch.object(chat_routes, "build_compaction_model", return_value=None),
            patch.object(chat_routes, "_execute_agent_run", new_callable=AsyncMock) as execute,
            patch.object(chat_routes, "agent_run_manager", lease_seconds=120, worker_id="template-test-worker"),
            patch.object(chat_routes, "_require_agent_capacity"),
        ):
            result = asyncio.run(start())
        request = self.db.get(ChatMessage, result.user_message_id)
        self.assertEqual(request.template_refs, [{"id": first.id, "name": first.name}])
        self.assertEqual([item["id"] for item in execute.call_args.kwargs["attached_templates"]], [first.id])
        self.assertEqual([item.id for item in session_attached_templates(self.db, self.session.id)], [second.id])
