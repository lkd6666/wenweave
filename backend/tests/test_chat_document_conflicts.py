import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register referenced tables in the isolated database.
from app.api.routes import chat
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.user import User
from app.services.chat_agent import ThinkingStatus
from app.services.document_versions import create_document_version, materialize_document_version


SOURCE = '<section><img src="/original.png"><p>正文</p></section>'
IMAGE_CHECKPOINT = SOURCE.replace('/original.png', '/edited.png')


class ChatDocumentConflictTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            'sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.manager = Mock(
            worker_id='conflict-test-worker',
            mark_started=AsyncMock(return_value=False),
            publish=AsyncMock(),
            mark_terminal=AsyncMock(),
            is_cancel_requested=Mock(return_value=False),
        )
        with self.Session() as db:
            db.add_all([
                User(id=1, username='conflict-test', password_hash='unused'),
                AIProvider(id=1, name='test', provider_type=ProviderType.OPENAI_COMPATIBLE,
                           base_url='https://example.invalid'),
                AIModel(id=1, provider_id=1, model_name='test', display_name='test'),
                Document(id=1, owner_id=1, title='冲突回归测试', current_html=SOURCE),
                ChatSession(id=1, document_id=1, title='测试'),
                ChatMessage(id=1, document_id=1, session_id=1, role=MessageRole.USER,
                            content='测试图片后还原正文', html_before=SOURCE),
                AgentRun(id='test-run', document_id=1, session_id=1, user_id=1,
                         user_message_id=1, client_request_id='test-request',
                         status=AgentRunStatus.RUNNING, owner_id=self.manager.worker_id),
            ])
            db.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    async def execute(self, candidate: str = SOURCE, *, own_image_write: bool = True,
                      external_html: str | None = None, outcome: str = 'final') -> dict:
        async def events(_model, _title, _source, _request, _map, _memory, _history,
                         _selection, _reference, edit_session, *_args, **_kwargs):
            if own_image_write:
                # Image application tools commit immediately, before later source edits.
                with self.Session() as db:
                    document = db.get(Document, 1)
                    document.current_html = IMAGE_CHECKPOINT
                    create_document_version(db, document, 1, DocumentVersionSource.AI, 'AI 编辑图片')
                    db.commit()
                edit_session.apply_external_image_change(edit_session.source_file().revision, IMAGE_CHECKPOINT)
                edit_session.persist_checkpoint()
                yield {'event': 'tool_result', 'data': {
                    'name': 'apply_edited_image', 'result': '图片已替换', 'html': edit_session.html,
                }}
            if candidate != edit_session.html:
                edit_session.write_source(edit_session.source_file().revision, candidate)
                edit_session.persist_checkpoint()
                yield {'event': 'tool_result', 'data': {
                    'name': 'edit_file', 'result': '正文已更新', 'html': edit_session.html,
                }}
            if external_html is not None:
                with self.Session() as db:
                    document = db.get(Document, 1)
                    document.current_html = external_html
                    create_document_version(db, document, 1, DocumentVersionSource.MANUAL, '手动保存')
                    db.commit()
            if outcome == 'cancelled':
                raise asyncio.CancelledError
            if outcome == 'error':
                yield {'event': 'error', 'data': {'message': 'provider disconnected'}}
            else:
                yield {'event': 'final', 'data': {'content': '操作完成。', 'html': edit_session.html}}

        with (
            patch.object(chat, 'SessionLocal', self.Session),
            patch.object(chat, 'agent_run_manager', self.manager),
            patch.object(chat, 'run_agent_loop', events),
            patch.object(chat, 'get_chat_context', return_value={}),
        ):
            await chat._execute_agent_run(
                run_id='test-run', document_id=1, session_id=1, user_id=1,
                chat_model=None, thinking_status=ThinkingStatus('auto', False, ''),
                document_title='冲突回归测试', current_html=SOURCE,
                user_message='测试图片后还原正文', user_message_id=1, model_id=1,
                compaction_model=None, image_attachment_ids=[], selected_elements=[],
            )
        finals = [call.args[2] for call in self.manager.publish.await_args_list if call.args[1] == 'final']
        self.assertEqual(len(finals), 1)
        return finals[0]

    def assert_restored(self, final: dict, status: AgentRunStatus) -> None:
        self.assertEqual(final['run_status'], status.value)
        self.assertEqual(final['html'], SOURCE)
        self.assertFalse(final['html_changed'])
        self.assertEqual(final['partial_save_state'], 'none')
        self.assertNotIn('外部修改', final['error_message'])
        with self.Session() as db:
            self.assertEqual(db.get(Document, 1).current_html, SOURCE)
            run = db.get(AgentRun, 'test-run')
            self.assertEqual(run.status, status)
            self.assertEqual(run.checkpoint_html, SOURCE)
            message = db.get(ChatMessage, run.assistant_message_id)
            self.assertIsNone(message.html_after)  # No net body change to undo.
            versions = db.scalars(select(DocumentVersion).order_by(DocumentVersion.version_number)).all()
            self.assertEqual(len(versions), 2)
            self.assertEqual(materialize_document_version(db, versions[0]), IMAGE_CHECKPOINT)
            self.assertEqual(materialize_document_version(db, versions[1]), SOURCE)

    async def test_own_image_write_then_restore_original_saves_without_conflict(self) -> None:
        self.assert_restored(await self.execute(), AgentRunStatus.COMPLETED)

    async def test_cancellation_preserves_completed_restore(self) -> None:
        self.assert_restored(await self.execute(outcome='cancelled'), AgentRunStatus.CANCELLED)

    async def test_provider_failure_preserves_completed_restore(self) -> None:
        self.assert_restored(await self.execute(outcome='error'), AgentRunStatus.FAILED)

    async def test_final_edit_can_replace_own_image_checkpoint(self) -> None:
        candidate = IMAGE_CHECKPOINT.replace('正文', '新正文')
        final = await self.execute(candidate)
        self.assertEqual(final['run_status'], 'completed')
        self.assertTrue(final['html_changed'])
        with self.Session() as db:
            self.assertEqual(db.get(Document, 1).current_html, candidate)
            message = db.get(ChatMessage, db.get(AgentRun, 'test-run').assistant_message_id)
            self.assertEqual(message.html_before, SOURCE)
            self.assertEqual(message.html_after, candidate)

    async def test_already_saved_image_is_not_duplicated(self) -> None:
        final = await self.execute(IMAGE_CHECKPOINT)
        self.assertEqual(final['run_status'], 'completed')
        self.assertTrue(final['html_changed'])
        with self.Session() as db:
            self.assertEqual(db.get(Document, 1).current_html, IMAGE_CHECKPOINT)
            self.assertEqual(len(db.scalars(select(DocumentVersion)).all()), 1)

    async def test_external_edit_is_protected_even_when_agent_restores_original(self) -> None:
        external = '<p>手动修改的正文</p>'
        final = await self.execute(external_html=external)
        self.assertEqual(final['run_status'], 'failed')
        self.assertEqual(final['partial_save_state'], 'conflict')
        self.assertEqual(final['html'], external)
        self.assertFalse(final['html_changed'])
        with self.Session() as db:
            self.assertEqual(db.get(Document, 1).current_html, external)
            self.assertEqual(len(db.scalars(select(DocumentVersion)).all()), 2)

    async def test_no_body_edit_creates_no_version(self) -> None:
        final = await self.execute(own_image_write=False)
        self.assertEqual(final['run_status'], 'completed')
        self.assertFalse(final['html_changed'])
        with self.Session() as db:
            self.assertEqual(db.get(Document, 1).current_html, SOURCE)
            self.assertEqual(db.scalars(select(DocumentVersion)).all(), [])
