import json
import unittest
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.chat import (
    _get_chat_session,
    _session_read,
    _session_message_query,
    archive_chat_session,
    create_chat_session,
    get_chat_context,
    list_messages,
    list_chat_sessions,
    replace_chat_session_template_attachments,
    remove_chat_session_template_attachment,
    restore_chat_session,
    restore_chat_session_context,
    truncate_chat_session_context,
)
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_session import ChatSession, ChatSessionMemory
from app.models.chat_session_layout_reference import ChatSessionLayoutReference
from app.models.document import Document
from app.models.gzh_theme_proposal import GzhThemeProposal, GzhThemeProposalStatus
from app.models.model_call_record import ModelCallRecord, ModelCallSource, ModelCallStatus
from app.models.template_library import TemplateLibraryItem, TemplateSourceType
from app.models.user import User, UserRole
from app.schemas.chat import ChatSessionCreate, ChatSessionTemplateAttachmentsUpdate
from app.services.layout_reference import (
    clear_session_layout_reference,
    get_session_layout_reference,
    session_layout_reference_agent_payload,
    session_layout_reference_summary,
)
from app.services.chat_session_context import (
    bind_session_theme_proposal,
    clear_session_theme_proposal,
    replace_session_attached_templates,
    session_attached_templates,
    session_approved_theme_proposal,
)
from app.services.agent_context import ContextRecord, context_prefix_hash


class ChatSessionRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            username="admin",
            display_name="管理员",
            password_hash="not-used-in-route-test",
            role=UserRole.ADMIN,
        )
        self.db.add(self.user)
        self.db.flush()
        self.document = Document(owner_id=self.user.id, title="测试稿", current_html="<p>正文</p>")
        self.db.add(self.document)
        self.db.flush()
        self.primary = ChatSession(document_id=self.document.id, title="初始对话")
        self.other = ChatSession(document_id=self.document.id, title="另一个任务")
        self.db.add_all([self.primary, self.other])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def add_message(self, session: ChatSession, content: str, role: MessageRole = MessageRole.USER) -> ChatMessage:
        item = ChatMessage(
            document_id=self.document.id,
            session_id=session.id,
            role=role,
            content=content,
        )
        self.db.add(item)
        self.db.flush()
        return item

    def test_context_get_persists_recovered_snapshot_after_refresh(self) -> None:
        provider = AIProvider(name="context-test", provider_type=ProviderType.OPENAI_COMPATIBLE,
                              base_url="https://example.invalid")
        self.db.add(provider)
        self.db.flush()
        model = AIModel(provider_id=provider.id, model_name="test", display_name="test",
                        context_window_tokens=800_000, context_compaction_threshold_tokens=500_000,
                        max_output_tokens=1_000, tool_result_max_tokens=1_000)
        self.db.add(model)
        first = self.add_message(self.primary, "旧进度", MessageRole.ASSISTANT)
        second = self.add_message(self.primary, "继续")
        initial = [
            ChatContextEvent(document_id=self.document.id, session_id=self.primary.id,
                             message_id=first.id, ordinal=0, kind=ContextEventKind.ASSISTANT,
                             payload_json='{"content":"旧进度"}', created_at=datetime(2026, 9, 25, 20, 12)),
            ChatContextEvent(document_id=self.document.id, session_id=self.primary.id,
                             message_id=second.id, ordinal=0, kind=ContextEventKind.USER,
                             payload_json='{"content":"继续"}', created_at=datetime(2026, 9, 25, 20, 12)),
        ]
        self.db.add_all(initial)
        self.db.flush()
        records = [ContextRecord(row.id, row.message_id, row.kind.value, row.payload) for row in initial]
        snapshot = ChatContextSnapshot(
            session_id=self.primary.id, compacted_through_event_id=initial[-1].id,
            compacted_through_message_id=second.id, retained_from_event_id=initial[-1].id + 1,
            summary_json='{"objective":"继续排版"}', source_event_count=2,
            source_prefix_hash=context_prefix_hash(records), is_active=False, active_slot=None,
            invalidation_reason="source_diverged", created_at=datetime(2026, 9, 25, 20, 14),
        )
        self.db.add(snapshot)
        self.db.add(ChatContextEvent(
            document_id=self.document.id, session_id=self.primary.id, message_id=first.id,
            ordinal=1, kind=ContextEventKind.ASSISTANT,
            payload_json='{"content":"晚到的工具结果"}', created_at=datetime(2026, 9, 25, 20, 26),
        ))
        self.db.commit()

        preview = get_chat_context(self.document.id, model.id, self.primary.id, self.user, self.db)
        self.assertEqual(preview["snapshot_id"], snapshot.id)
        self.assertFalse(preview["requires_compaction"])
        with Session(self.engine) as fresh:
            persisted = fresh.get(ChatContextSnapshot, snapshot.id)
            self.assertTrue(persisted.is_active)
            self.assertEqual(persisted.source_max_event_id, initial[-1].id)

    def test_truncation_hides_only_the_current_session_and_clears_its_memory(self) -> None:
        first = self.add_message(self.primary, "旧约束")
        second = self.add_message(self.primary, "旧结果", MessageRole.ASSISTANT)
        other = self.add_message(self.other, "另一任务的约束")
        self.db.add(
            ChatSessionMemory(
                session_id=self.primary.id,
                compacted_through_message_id=second.id,
                summary_json=json.dumps({"user_preferences": ["旧约束"]}, ensure_ascii=False),
            )
        )
        self.db.commit()

        result = truncate_chat_session_context(self.document.id, self.primary.id, self.user, self.db)

        self.assertEqual(result["hidden_message_count"], 2)
        self.assertEqual(result["visible_message_count"], 0)
        self.assertEqual(_session_message_query(self.db, self.primary).count(), 0)
        self.assertEqual(_session_message_query(self.db, self.primary, include_hidden=True).count(), 2)
        self.assertEqual(_session_message_query(self.db, self.other).one().id, other.id)
        self.assertIsNone(self.db.query(ChatSessionMemory).filter_by(session_id=self.primary.id).first())

        fresh = self.add_message(self.primary, "截断后的新请求")
        self.db.commit()
        self.assertEqual(_session_message_query(self.db, self.primary).one().id, fresh.id)

        restored = restore_chat_session_context(self.document.id, self.primary.id, self.user, self.db)
        self.assertEqual(restored["hidden_message_count"], 0)
        self.assertEqual(_session_message_query(self.db, self.primary).count(), 3)
        self.assertEqual(first.id, _session_message_query(self.db, self.primary).order_by(ChatMessage.id).first().id)

    def test_archive_is_recoverable_and_new_sessions_start_empty(self) -> None:
        self.add_message(self.primary, "旧消息")
        created = create_chat_session(
            self.document.id,
            ChatSessionCreate(title="新的排版任务"),
            self.user,
            self.db,
        )
        new_session = _get_chat_session(self.db, self.document.id, created["id"])
        self.assertEqual(_session_message_query(self.db, new_session).count(), 0)

        archived = archive_chat_session(self.document.id, self.primary.id, self.user, self.db)
        self.assertTrue(archived["is_archived"])
        with self.assertRaises(HTTPException):
            _get_chat_session(self.db, self.document.id, self.primary.id, allow_archived=False)

        restored = restore_chat_session(self.document.id, self.primary.id, self.user, self.db)
        self.assertFalse(restored["is_archived"])
        self.assertEqual(_session_message_query(self.db, self.primary).count(), 1)

    def test_empty_default_session_is_reused_but_archived_or_used_sessions_are_not(self) -> None:
        first = create_chat_session(
            self.document.id,
            ChatSessionCreate(),
            self.user,
            self.db,
        )
        repeated = create_chat_session(
            self.document.id,
            ChatSessionCreate(),
            self.user,
            self.db,
        )
        self.assertEqual(repeated["id"], first["id"])

        first_session = _get_chat_session(self.db, self.document.id, first["id"])
        self.add_message(first_session, "第一条消息")
        self.db.commit()
        next_empty = create_chat_session(
            self.document.id,
            ChatSessionCreate(),
            self.user,
            self.db,
        )
        self.assertNotEqual(next_empty["id"], first["id"])

        archive_chat_session(self.document.id, next_empty["id"], self.user, self.db)
        replacement = create_chat_session(
            self.document.id,
            ChatSessionCreate(),
            self.user,
            self.db,
        )
        self.assertNotEqual(replacement["id"], next_empty["id"])

    def test_listing_legacy_document_sessions_creates_an_active_default(self) -> None:
        legacy_document = Document(owner_id=self.user.id, title="旧稿", current_html="<p>正文</p>")
        self.db.add(legacy_document)
        self.db.commit()

        sessions = list_chat_sessions(legacy_document.id, False, self.user, self.db)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["title"], "新对话")
        self.assertFalse(sessions[0]["is_archived"])

    def test_listing_messages_with_chat_image_attachments_serializes_orm_rows(self) -> None:
        message = self.add_message(self.primary, "请参考这张图")
        self.db.add(
            ChatImageAttachment(
                id="attachment-1",
                document_id=self.document.id,
                uploader_id=self.user.id,
                message_id=message.id,
                filename="reference.png",
                content_type="image/png",
                size=128,
                storage_mode="local",
                object_key="local/chat-images/attachment-1.png",
            )
        )
        self.db.commit()

        messages = list_messages(self.document.id, self.primary.id, False, self.user, self.db)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["image_attachments"][0]["filename"], "reference.png")
        self.assertIn("/chat-images/attachment-1/content?token=", messages[0]["image_attachments"][0]["preview_url"])

    def test_listing_messages_pages_backward_within_visible_session(self) -> None:
        rows = [self.add_message(self.primary, f"消息 {index}") for index in range(7)]
        self.add_message(self.other, "其他对话")
        self.db.commit()
        self.primary.context_start_message_id = rows[0].id
        self.db.commit()

        latest = list_messages(self.document.id, self.primary.id, False, self.user, self.db, limit=3)
        older = list_messages(self.document.id, self.primary.id, False, self.user, self.db, limit=3, before_id=latest[0]["id"])

        self.assertEqual([item["id"] for item in latest], [row.id for row in rows[4:]])
        self.assertEqual([item["id"] for item in older], [row.id for row in rows[1:4]])
        self.assertEqual(
            [item["id"] for item in list_messages(self.document.id, self.primary.id, True, self.user, self.db, limit=3, before_id=older[0]["id"])],
            [rows[0].id],
        )

    def test_listing_messages_includes_the_request_author(self) -> None:
        collaborator = User(
            username="collaborator",
            display_name="协作用户",
            password_hash="not-used-in-route-test",
            role=UserRole.USER,
        )
        self.db.add(collaborator)
        self.db.flush()
        message = ChatMessage(
            document_id=self.document.id,
            session_id=self.primary.id,
            created_by_id=collaborator.id,
            role=MessageRole.USER,
            content="由协作用户发送的请求",
        )
        self.db.add(message)
        self.db.commit()

        messages = list_messages(self.document.id, self.primary.id, False, self.user, self.db)

        self.assertEqual(messages[0]["created_by"], {
            "id": collaborator.id,
            "username": "collaborator",
            "display_name": "协作用户",
        })

    def test_listing_assistant_message_includes_run_model_usage(self) -> None:
        provider = AIProvider(name="测试服务商", provider_type=ProviderType.OPENAI_COMPATIBLE, base_url="https://example.test")
        self.db.add(provider)
        self.db.flush()
        model = AIModel(provider_id=provider.id, model_name="test-model", display_name="测试模型")
        self.db.add(model)
        request = self.add_message(self.primary, "调整标题")
        response = self.add_message(self.primary, "已调整标题", MessageRole.ASSISTANT)
        run = AgentRun(
            id="model-usage-run",
            document_id=self.document.id,
            session_id=self.primary.id,
            user_id=self.user.id,
            user_message_id=request.id,
            assistant_message_id=response.id,
            client_request_id="model-usage-request",
            status=AgentRunStatus.COMPLETED,
        )
        now = datetime.now(timezone.utc)
        self.db.add_all([
            run,
            ModelCallRecord(
                model_id=model.id,
                user_id=self.user.id,
                source=ModelCallSource.AGENT,
                source_id=run.id,
                status=ModelCallStatus.COMPLETED,
                usage_reported=True,
                input_tokens=120,
                output_tokens=20,
                cache_read_tokens=90,
                cache_write_tokens=10,
                started_at=now,
                finished_at=now,
            ),
            ModelCallRecord(
                model_id=model.id,
                user_id=self.user.id,
                source=ModelCallSource.AGENT_RUNTIME_COMPACTION,
                source_id=run.id,
                status=ModelCallStatus.COMPLETED,
                usage_reported=True,
                input_tokens=40,
                output_tokens=5,
                cache_read_tokens=30,
                cache_write_tokens=5,
                started_at=now,
                finished_at=now,
            ),
        ])
        self.db.commit()

        messages = list_messages(self.document.id, self.primary.id, False, self.user, self.db)
        usage = next(item["model_usage"] for item in messages if item["id"] == response.id)

        self.assertEqual(usage, {
            "model_names": ["测试模型"],
            "input_tokens": 160,
            "output_tokens": 25,
            "total_tokens": 185,
            "cache_read_tokens": 120,
            "cache_write_tokens": 15,
            "cache_hit_rate": 75,
            "call_count": 2,
            "usage_reported": True,
        })

    def test_bound_layout_reference_survives_context_truncation_and_can_be_cleared(self) -> None:
        binding = ChatSessionLayoutReference(
            session_id=self.primary.id,
            canonical_url="https://mp.weixin.qq.com/s/reference",
            title="参考模板",
            site_name="mp.weixin.qq.com",
            extracted_from="公众号正文",
            html_template='<section style="background:url(/api/documents/local-images/tape.png)"><p>参考文字</p></section>',
            block_count=2,
            image_slots=1,
            image_assets=1,
            imitation_strength="maximum",
        )
        self.db.add(binding)
        self.db.commit()

        truncate_chat_session_context(self.document.id, self.primary.id, self.user, self.db)
        active = get_session_layout_reference(self.db, self.primary.id)
        payload = session_layout_reference_agent_payload(active)

        self.assertIsNotNone(payload)
        self.assertIn("/api/documents/local-images/tape.png", payload["html"])
        self.assertNotIn("canonical_url", payload)
        self.assertEqual(payload["imitation_strength"], "maximum")
        self.assertEqual(session_layout_reference_summary(active)["imitation_strength"], "maximum")
        self.assertTrue(clear_session_layout_reference(self.db, self.primary.id))
        self.db.commit()
        self.assertIsNone(get_session_layout_reference(self.db, self.primary.id))

    def test_templates_and_theme_are_durable_per_session_and_survive_context_reset(self) -> None:
        first = TemplateLibraryItem(name="首个组件", html="<section>first</section>", source_type=TemplateSourceType.SOURCE)
        second = TemplateLibraryItem(name="第二个组件", html="<section>second</section>", source_type=TemplateSourceType.SOURCE)
        proposal = GzhThemeProposal(
            id="7c4fd569-362d-46e2-bd40-2a7a5cb368c8",
            document_id=self.document.id,
            session_id=self.primary.id,
            user_id=self.user.id,
            theme_key="news-standard",
            theme_name="新闻主题",
            theme_markdown="# theme",
            base_checksum="a" * 64,
            status=GzhThemeProposalStatus.APPROVED,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        self.db.add_all([first, second, proposal])
        self.db.flush()

        replace_session_attached_templates(self.db, self.primary.id, [second.id, first.id])
        bind_session_theme_proposal(self.db, self.primary.id, proposal.id)
        self.db.commit()

        read = _session_read(self.db, self.primary)
        self.assertEqual([item["name"] for item in read["attached_templates"]], ["第二个组件", "首个组件"])
        self.assertEqual(read["theme_context"]["proposal_id"], proposal.id)
        self.assertEqual(read["theme_context"]["theme_name"], "新闻主题")
        self.assertEqual(session_attached_templates(self.db, self.other.id), [])
        self.assertIsNone(_session_read(self.db, self.other)["theme_context"])

        truncate_chat_session_context(self.document.id, self.primary.id, self.user, self.db)
        self.assertEqual([item.id for item in session_attached_templates(self.db, self.primary.id)], [second.id, first.id])
        self.assertEqual(_session_read(self.db, self.primary)["theme_context"]["proposal_id"], proposal.id)

        self.assertTrue(clear_session_theme_proposal(self.db, self.primary.id))
        self.db.commit()
        self.assertIsNone(_session_read(self.db, self.primary)["theme_context"])

    def test_template_references_can_change_while_a_run_keeps_its_request_snapshot(self) -> None:
        first = TemplateLibraryItem(name="First", html="<p>First</p>", source_type=TemplateSourceType.SOURCE)
        second = TemplateLibraryItem(name="Second", html="<p>Second</p>", source_type=TemplateSourceType.SOURCE)
        self.db.add_all([first, second])
        self.db.flush()
        replace_session_attached_templates(self.db, self.primary.id, [first.id])
        request = self.add_message(self.primary, "Edit article")
        request.template_refs_json = json.dumps([{"id": first.id, "name": first.name}])
        run = AgentRun(
            id="template-reference-run", document_id=self.document.id, session_id=self.primary.id,
            user_id=self.user.id, user_message_id=request.id, client_request_id="template-reference-request",
            status=AgentRunStatus.RUNNING,
        )
        self.db.add(run)
        self.db.commit()
        for run_status in (AgentRunStatus.PENDING, AgentRunStatus.RUNNING, AgentRunStatus.WAITING_FOR_INPUT):
            with self.subTest(status=run_status):
                run.status = run_status
                self.db.commit()
                result = replace_chat_session_template_attachments(
                    self.document.id, self.primary.id,
                    ChatSessionTemplateAttachmentsUpdate(template_ids=[first.id, second.id]), self.user, self.db,
                )
                self.assertEqual([item["id"] for item in result["attached_templates"]], [first.id, second.id])
                result = remove_chat_session_template_attachment(
                    self.document.id, self.primary.id, first.id, self.user, self.db,
                )
                self.assertEqual([item["id"] for item in result["attached_templates"]], [second.id])
                self.assertEqual(request.template_refs, [{"id": first.id, "name": first.name}])
                self.assertEqual(run.status, run_status)
                self.assertEqual(self.document.current_html, "<p>正文</p>")
                self.assertEqual(session_attached_templates(self.db, self.other.id), [])
                with self.assertRaises(HTTPException) as raised:
                    truncate_chat_session_context(self.document.id, self.primary.id, self.user, self.db)
                self.assertEqual(raised.exception.status_code, 409)

    def test_archived_session_template_references_cannot_be_changed(self) -> None:
        self.primary.is_archived = True
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            replace_chat_session_template_attachments(
                self.document.id, self.primary.id,
                ChatSessionTemplateAttachmentsUpdate(template_ids=[]), self.user, self.db,
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_approved_theme_remains_available_to_continue_its_initial_application(self) -> None:
        proposal = GzhThemeProposal(
            id="06e19145-6613-47d8-9bd1-e9ea6a7b9a28",
            document_id=self.document.id,
            session_id=self.primary.id,
            user_id=self.user.id,
            theme_key="news-standard",
            theme_name="新闻主题",
            theme_markdown="# theme",
            base_checksum="a" * 64,
            status=GzhThemeProposalStatus.APPROVED,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        self.db.add(proposal)
        self.db.flush()
        bind_session_theme_proposal(self.db, self.primary.id, proposal.id)

        continued_proposal = session_approved_theme_proposal(self.db, self.primary.id)
        self.assertIsNotNone(continued_proposal)
        assert continued_proposal is not None
        self.assertEqual(continued_proposal.id, proposal.id)

        proposal.status = GzhThemeProposalStatus.APPLIED
        self.assertIsNone(session_approved_theme_proposal(self.db, self.primary.id))


if __name__ == "__main__":
    unittest.main()
