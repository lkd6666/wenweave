import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register referenced tables in the isolated database.
from app.api.routes import chat, documents, image_generations
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.chat_user_question import ChatUserQuestion, ChatUserQuestionStatus
from app.models.document import Document
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.user import User
from app.schemas.chat import ChatRevertRequest, ChatUserQuestionAnswerRequest
from app.schemas.document import DocumentHtmlPatch, DocumentUpdate
from app.services.chat_agent import ThinkingStatus, serialise_resume_messages
from app.services.document_versions import content_checksum, create_document_version, materialize_document_version


SOURCE = '<section><img src="/original.png"><p>正文</p></section>'
IMAGE_CHECKPOINT = SOURCE.replace('/original.png', '/edited.png')


class ChatDocumentConflictTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_after_direct_image_checkpoint_saves_later_text_candidate(self) -> None:
        from app.services.agent_checkpoints import checkpoint_save_state
        candidate = IMAGE_CHECKPOINT.replace('正文', '后续修改')
        with self.Session() as db:
            document = db.get(Document, 1)
            document.current_html = IMAGE_CHECKPOINT
            run = db.get(AgentRun, 'test-run')
            run.checkpoint_document_html = IMAGE_CHECKPOINT
            run.checkpoint_html = candidate
            db.commit()
            save_state, html, changed = checkpoint_save_state(db, run, document, label='test recovery')
            self.assertEqual(save_state, 'preserved')
            self.assertTrue(changed)
            self.assertEqual(html, candidate)
            self.assertEqual(document.current_html, candidate)

    async def test_terminal_message_status_and_final_event_are_atomic_before_notification(self) -> None:
        from app.models.agent_run_event import AgentRunEvent
        from app.services.agent_run_manager import AgentRunManager
        import app.services.agent_run_manager as manager_module
        checked = []

        async def before_notify(run_id, _sequence, event, _data, **_kwargs):
            self.assertEqual(event, 'final')
            # This is the old race window: result/status committed, but local
            # terminal notification has not run. A different worker must already
            # be able to replay final and its saved message.
            with self.Session() as db:
                run = db.get(AgentRun, run_id)
                if run.status not in {AgentRunStatus.COMPLETED, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}:
                    return
                message = db.get(ChatMessage, run.assistant_message_id)
                final = db.query(AgentRunEvent).filter_by(run_id=run_id, event='final').one()
                payload = json.loads(final.payload_json)
                self.assertEqual(payload['content'], message.content)
                self.assertEqual(payload['run_status'], run.status.value)
                self.assertEqual(run.event_sequence, final.sequence)
            with patch.object(manager_module, 'SessionLocal', self.Session):
                reader = AgentRunManager()
                frames = [item async for item in reader.events_after(run_id, 0)]
            self.assertEqual(frames[-1].event, 'final')
            self.assertEqual(frames[-1].data['content'], message.content)
            checked.append(run.status.value)

        self.manager.notify_persisted_event.side_effect = before_notify
        result = await self.execute(own_image_write=False)
        self.assertEqual(result['run_status'], 'completed')
        self.assertEqual(checked, ['completed'])
        self.manager.notify_persisted_event.assert_awaited_once()
        self.assertFalse(any(call.args[1] == 'final' for call in self.manager.publish.await_args_list))
        calls = self.manager.mock_calls
        self.assertLess(next(i for i, call in enumerate(calls) if call[0] == 'flush'),
                        next(i for i, call in enumerate(calls) if call[0] == 'notify_persisted_event'))

    async def test_real_event_manager_flushes_prefix_before_committing_final(self) -> None:
        from app.models.agent_run_event import AgentRunEvent
        from app.services.agent_run_manager import AgentRunManager
        import app.services.agent_run_manager as manager_module
        manager = AgentRunManager()
        manager.worker_id = self.manager.worker_id
        manager.flush_interval_seconds = 60
        manager.create('test-run')
        original_publish = manager.publish
        local_final_checks = []

        async def publish(run_id, event, data, **kwargs):
            if event == 'context_stats' and kwargs.get('force'):
                # Later telemetry must never advance a local subscriber past
                # a final event that has not yet entered its local cache.
                frames, has_gap = await manager._local_durable_events_after(manager.get(run_id), 0)
                self.assertFalse(has_gap)
                self.assertEqual(frames[-1].event, 'final')
                local_final_checks.append(frames[-1].sequence)
            await original_publish(run_id, event, data, **kwargs)

        async def graph(*_args, **_kwargs):
            yield {'event': 'text_delta', 'data': {'text': '已完成比对。'}}
            yield {'event': 'context_stats', 'data': {'used_tokens': 1234, 'state': 'streaming'}}
            yield {'event': 'final', 'data': {'content': '已完成比对。', 'html': SOURCE}}

        with (patch.object(chat, 'SessionLocal', self.Session),
              patch.object(manager_module, 'SessionLocal', self.Session),
              patch.object(chat, 'agent_run_manager', manager),
              patch.object(chat, 'run_agent_loop', graph),
              patch.object(chat, 'get_chat_context', return_value={}),
              patch.object(manager, 'publish', side_effect=publish),
              patch.object(manager_module.logger, 'warning') as warning):
            await chat._execute_agent_run(run_id='test-run', document_id=1, session_id=1, user_id=1,
                chat_model=None, thinking_status=ThinkingStatus('auto', False, ''),
                document_title='比对', current_html=SOURCE, user_message='只做比对', user_message_id=1,
                model_id=1, compaction_model=None, image_attachment_ids=[], selected_elements=[])
            if manager.get('test-run').eviction_task:
                manager.get('test-run').eviction_task.cancel()
            self.assertFalse(any('batch_rejected' in str(call) for call in warning.call_args_list))
            self.assertEqual(len(local_final_checks), 1)
            with self.Session() as db:
                events = db.query(AgentRunEvent).filter_by(run_id='test-run').order_by(AgentRunEvent.sequence).all()
                names = [item.event for item in events]
                self.assertEqual(names.count('final'), 1)
                self.assertLess(names.index('text_delta'), names.index('final'))
                self.assertIn('context_stats', names[:names.index('final')])
                self.assertEqual(db.get(AgentRun, 'test-run').status, AgentRunStatus.COMPLETED)
            reader = AgentRunManager()
            frames = [item async for item in reader.events_after('test-run', 0)]
            self.assertEqual([item.data['content'] for item in frames if item.event == 'final'], ['已完成比对。'])

    async def test_empty_document_is_a_recoverable_completed_edit(self) -> None:
        from app.services.agent_checkpoints import checkpoint_save_state
        with patch.object(chat, 'SessionLocal', self.Session), patch.object(chat, 'agent_run_manager', self.manager):
            with self.Session() as db:
                run = db.get(AgentRun, 'test-run')
                run.status = AgentRunStatus.RUNNING
                run.owner_id = self.manager.worker_id
                db.commit()
            chat._persist_run_checkpoint('test-run', '')
        with self.Session() as db:
            run = db.get(AgentRun, 'test-run')
            self.assertEqual(run.checkpoint_document_html, SOURCE)
            save_state, html, changed = checkpoint_save_state(db, run, db.get(Document, 1), label='empty edit')
            self.assertEqual((save_state, html, changed), ('preserved', '', True))

    async def test_all_active_states_reject_manual_document_mutations(self) -> None:
        for run_status in (AgentRunStatus.PENDING, AgentRunStatus.RUNNING,
                           AgentRunStatus.WAITING_FOR_INPUT, AgentRunStatus.CANCELLING):
            with self.Session() as db:
                db.get(AgentRun, 'test-run').status = run_status
                db.commit()
            operations = [
                lambda db, user: documents.update_document(1, DocumentUpdate(current_html='<p>external</p>'), user, db),
                lambda db, user: documents.update_document(1, DocumentUpdate(title='external'), user, db),
                lambda db, user: documents.patch_document_content(1, DocumentHtmlPatch(
                    base_checksum=content_checksum(SOURCE), prefix_length=0, suffix_length=0,
                    replacement='<p>external</p>'), user, db),
                lambda db, user: documents.restore_document_version(1, 999, user, db),
                lambda db, user: documents.revert_last_ai_change(1, user, db),
                lambda db, user: documents.revert_to_message(1, ChatRevertRequest(message_id=1), user, db),
                lambda db, user: documents.delete_document(1, user, db),
                lambda db, _user: image_generations._require_idle_document(db, 1),
            ]
            for operation in operations:
                with self.subTest(status=run_status, operation=operations.index(operation)), self.Session() as db:
                    with self.assertRaises(HTTPException) as caught:
                        operation(db, db.get(User, 1))
                    self.assertEqual(caught.exception.status_code, 409)
                    db.rollback()
                    self.assertEqual(db.get(Document, 1).current_html, SOURCE)

    async def test_stop_waiting_preserves_candidate_and_original_undo_baseline(self) -> None:
        candidate = IMAGE_CHECKPOINT.replace('正文', '已完成修改')
        paused = await self.execute(candidate, outcome='question')
        with self.Session() as db, patch.object(chat, 'agent_run_manager', self.manager):
            result = await chat.cancel_chat_run(1, 'test-run', db.get(User, 1), db)
            self.assertEqual(result.status, AgentRunStatus.CANCELLED)
            self.assertEqual(db.get(Document, 1).current_html, candidate)
            message = db.get(ChatMessage, result.assistant_message_id)
            self.assertEqual(message.html_before, SOURCE)
            self.assertEqual(message.html_after, candidate)
            self.assertEqual(db.get(ChatUserQuestion, paused['id']).status, ChatUserQuestionStatus.CANCELLED)
            await chat.cancel_chat_run(1, 'test-run', db.get(User, 1), db)
            self.assertEqual(db.query(ChatMessage).filter(ChatMessage.role == MessageRole.ASSISTANT).count(), 1)
        self.assertEqual(self.manager.publish.await_args.args[2]['partial_save_state'], 'preserved')

    async def test_stop_waiting_keeps_real_external_changes(self) -> None:
        await self.execute(SOURCE.replace('正文', '候选'), own_image_write=False, outcome='question')
        with self.Session() as db:
            db.get(Document, 1).current_html = '<p>external change</p>'
            db.commit()
        with self.Session() as db, patch.object(chat, 'agent_run_manager', self.manager):
            await chat.cancel_chat_run(1, 'test-run', db.get(User, 1), db)
            self.assertEqual(db.get(Document, 1).current_html, '<p>external change</p>')
        self.assertEqual(self.manager.publish.await_args.args[2]['partial_save_state'], 'conflict')

    async def test_timeout_permanent_conflict_finishes_instead_of_retrying_forever(self) -> None:
        from datetime import datetime, timedelta, timezone
        paused = await self.execute(own_image_write=False, outcome='question')
        with self.Session() as db:
            db.get(Document, 1).current_html = '<p>external change</p>'
            db.get(ChatUserQuestion, paused['id']).timeout_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        with patch.object(chat, 'SessionLocal', self.Session), patch.object(chat, 'agent_run_manager', self.manager):
            self.assertTrue(await chat._auto_answer_timed_out_user_question(paused['id']))
        with self.Session() as db:
            self.assertEqual(db.get(AgentRun, 'test-run').status, AgentRunStatus.FAILED)
            self.assertEqual(db.get(ChatUserQuestion, paused['id']).status, ChatUserQuestionStatus.CANCELLED)
            self.assertEqual(db.get(Document, 1).current_html, '<p>external change</p>')

    async def test_timeout_extended_deadline_keeps_question_waiting(self) -> None:
        from datetime import datetime, timedelta, timezone
        paused = await self.execute(own_image_write=False, outcome='question')
        with self.Session() as db:
            db.get(ChatUserQuestion, paused['id']).timeout_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

        async def extend(*_args):
            with self.Session() as db:
                db.get(ChatUserQuestion, paused['id']).timeout_at = datetime.now(timezone.utc) + timedelta(seconds=60)
                db.commit()
            raise HTTPException(409, 'deadline refreshed')

        with (patch.object(chat, 'SessionLocal', self.Session),
              patch.object(chat, 'answer_chat_user_question', side_effect=extend)):
            self.assertFalse(await chat._auto_answer_timed_out_user_question(paused['id']))
        with self.Session() as db:
            self.assertEqual(db.get(ChatUserQuestion, paused['id']).status, ChatUserQuestionStatus.WAITING)

    async def test_timeout_model_initialization_failure_finishes_and_preserves_edits(self) -> None:
        from datetime import datetime, timedelta, timezone
        candidate = SOURCE.replace('正文', '已完成修改')
        paused = await self.execute(candidate, own_image_write=False, outcome='question')
        with self.Session() as db:
            db.get(ChatUserQuestion, paused['id']).timeout_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        with (patch.object(chat, 'SessionLocal', self.Session),
              patch.object(chat, 'agent_run_manager', self.manager),
              patch.object(chat, 'build_chat_model', side_effect=ValueError('invalid provider configuration'))):
            self.assertTrue(await chat._auto_answer_timed_out_user_question(paused['id']))
        with self.Session() as db:
            self.assertEqual(db.get(AgentRun, 'test-run').status, AgentRunStatus.FAILED)
            self.assertEqual(db.get(Document, 1).current_html, candidate)

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
            flush=AsyncMock(),
            mark_waiting=AsyncMock(),
            notify_persisted_event=AsyncMock(),
            is_cancel_requested=Mock(return_value=False),
        )
        async def mark_started(run_id: str) -> bool:
            with self.Session() as db:
                db.get(AgentRun, run_id).owner_id = self.manager.worker_id
                db.commit()
            return False

        self.manager.mark_started.side_effect = mark_started
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
                      external_html: str | None = None, outcome: str = 'final',
                      initial_html: str = SOURCE, resume_state: dict | None = None) -> dict:
        self.manager.publish.reset_mock()
        self.manager.notify_persisted_event.reset_mock()
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
            if outcome == 'question':
                call_id = str(uuid4())
                yield {'event': 'user_question', 'data': {
                    'question': {'question': '接下来选什么风格？', 'options': []},
                    'tool_call_id': call_id,
                    'resume_messages': serialise_resume_messages([AIMessage(content='', tool_calls=[{
                        'id': call_id, 'name': 'ask_user', 'args': {'question': '接下来选什么风格？'},
                    }])]),
                }}
            elif outcome == 'cancelled':
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
            patch.object(chat, 'schedule_user_question_timeout'),
        ):
            await chat._execute_agent_run(
                run_id='test-run', document_id=1, session_id=1, user_id=1,
                chat_model=None, thinking_status=ThinkingStatus('auto', False, ''),
                document_title='冲突回归测试', current_html=initial_html,
                user_message='测试图片后还原正文', user_message_id=1, model_id=1,
                compaction_model=None, image_attachment_ids=[], selected_elements=[],
                resume_state=resume_state,
            )
        if outcome == 'question':
            with self.Session() as db:
                question = db.scalars(select(ChatUserQuestion).where(
                    ChatUserQuestion.status == ChatUserQuestionStatus.WAITING,
                )).one_or_none()
                if question is not None:
                    return {'id': question.id, 'context': json.loads(question.execution_context_json)}
        finals = [call.args[2] for call in self.manager.publish.await_args_list if call.args[1] == 'final']
        finals += [call.args[3] for call in self.manager.notify_persisted_event.await_args_list if call.args[2] == 'final']
        self.assertEqual(len(finals), 1)
        return finals[0]

    async def answer(self, question_id: str) -> dict:
        execute = AsyncMock()
        with (
            self.Session() as db,
            patch.object(chat, 'agent_run_manager', self.manager),
            patch.object(chat, 'build_chat_model', return_value=(None, ThinkingStatus('auto', False, ''))),
            patch.object(chat, 'build_compaction_model', return_value=None),
            patch.object(chat, '_execute_agent_run', execute),
        ):
            result = await chat.answer_chat_user_question(
                1, 'test-run', question_id,
                ChatUserQuestionAnswerRequest(action='custom', custom_requirement='低圆角',
                                              client_request_id=str(uuid4())),
                db.get(User, 1), db,
            )
            self.assertEqual(result.status, AgentRunStatus.PENDING)
            await self.manager.set_task.call_args.args[1]
        execute.assert_awaited_once()
        return execute.call_args.kwargs

    async def test_question_after_unsaved_edit_resumes_and_saves_with_undo(self) -> None:
        candidate = SOURCE.replace('正文', '新正文')
        paused = await self.execute(candidate, own_image_write=False, outcome='question')
        self.assertEqual(paused['context']['document_html'], SOURCE)
        self.assertEqual(paused['context']['current_html'], candidate)
        resumed = await self.answer(paused['id'])
        self.assertEqual(resumed['current_html'], candidate)
        final = await self.execute(candidate, own_image_write=False, initial_html=resumed['current_html'],
                                   resume_state=resumed['resume_state'])
        self.assertEqual(final['run_status'], 'completed')
        self.assertTrue(final['html_changed'])
        with self.Session() as db:
            self.assertEqual(db.get(Document, 1).current_html, candidate)
            message = db.get(ChatMessage, db.get(AgentRun, 'test-run').assistant_message_id)
            self.assertEqual(message.html_before, SOURCE)
            self.assertEqual(message.html_after, candidate)

    async def test_question_after_direct_image_write_and_source_edit_resumes(self) -> None:
        candidate = IMAGE_CHECKPOINT.replace('正文', '新正文')
        paused = await self.execute(candidate, outcome='question')
        self.assertEqual(paused['context']['document_html'], IMAGE_CHECKPOINT)
        resumed = await self.answer(paused['id'])
        final = await self.execute(candidate, own_image_write=False, initial_html=resumed['current_html'],
                                   resume_state=resumed['resume_state'])
        self.assertEqual(final['run_status'], 'completed')
        self.assertTrue(final['html_changed'])
        with self.Session() as db:
            message = db.get(ChatMessage, db.get(AgentRun, 'test-run').assistant_message_id)
            self.assertEqual(message.html_before, SOURCE)

    async def test_serialization_during_question_keeps_source_revision_and_completes(self) -> None:
        paused = await self.execute(own_image_write=False, outcome='question')
        with self.Session() as db:
            db.get(Document, 1).current_html = SOURCE.replace('"', "'")
            db.commit()
        resumed = await self.answer(paused['id'])
        self.assertEqual(resumed['current_html'], SOURCE)
        final = await self.execute(own_image_write=False, initial_html=resumed['current_html'],
                                   resume_state=resumed['resume_state'])
        self.assertEqual(final['run_status'], 'completed')
        self.assertFalse(final['html_changed'])

    async def test_manual_save_cannot_format_document_while_waiting_for_answer(self) -> None:
        paused = await self.execute(own_image_write=False, outcome='question')
        formatted = '<section>\n  <img src="/original.png">\n  <p>正文</p>\n</section>'
        for save_kind in ('patch', 'update'):
            with (
                self.subTest(save_kind=save_kind), self.Session() as db,
                patch.object(documents, '_localize_html_for_document_save',
                             return_value=SimpleNamespace(html=formatted, localized_count=0)),
            ):
                with self.assertRaises(HTTPException) as error:
                    if save_kind == 'patch':
                        documents.patch_document_content(
                            1, DocumentHtmlPatch(base_checksum=content_checksum(SOURCE),
                                                 prefix_length=0, suffix_length=0, replacement=formatted),
                            db.get(User, 1), db,
                        )
                    else:
                        documents.update_document(
                            1, DocumentUpdate(current_html=formatted), db.get(User, 1), db,
                        )
                self.assertEqual(error.exception.status_code, 409)
                db.rollback()
                self.assertEqual(db.get(Document, 1).current_html, SOURCE)
                self.assertEqual(db.get(ChatUserQuestion, paused['id']).status, ChatUserQuestionStatus.WAITING)
        resumed = await self.answer(paused['id'])
        self.assertEqual(resumed['current_html'], SOURCE)

    async def test_legacy_unsaved_candidate_resumes_when_request_document_is_intact(self) -> None:
        candidate = SOURCE.replace('正文', '新正文')
        paused = await self.execute(candidate, own_image_write=False, outcome='question')
        with self.Session() as db:
            question = db.get(ChatUserQuestion, paused['id'])
            context = json.loads(question.execution_context_json)
            del context['document_html']
            question.execution_context_json = json.dumps(context)
            db.commit()
        resumed = await self.answer(paused['id'])
        self.assertEqual(resumed['current_html'], candidate)

    async def test_second_question_keeps_document_baseline_and_original_undo_source(self) -> None:
        candidate = SOURCE.replace('正文', '新正文')
        first = await self.execute(candidate, own_image_write=False, outcome='question')
        resumed = await self.answer(first['id'])
        second = await self.execute(candidate, own_image_write=False, outcome='question',
                                    initial_html=resumed['current_html'], resume_state=resumed['resume_state'])
        self.assertEqual(second['context']['document_html'], SOURCE)
        resumed = await self.answer(second['id'])
        final = await self.execute(candidate, own_image_write=False, initial_html=resumed['current_html'],
                                   resume_state=resumed['resume_state'])
        self.assertEqual(final['run_status'], 'completed')
        with self.Session() as db:
            message = db.get(ChatMessage, db.get(AgentRun, 'test-run').assistant_message_id)
            self.assertEqual(message.html_before, SOURCE)

    async def test_recorded_document_baseline_does_not_fall_back_to_original_request(self) -> None:
        paused = await self.execute(IMAGE_CHECKPOINT, outcome='question')
        with self.Session() as db:
            db.get(Document, 1).current_html = SOURCE
            db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.answer(paused['id'])
        self.assertEqual(error.exception.status_code, 409)

    async def test_real_edit_while_waiting_is_rejected_without_consuming_answer(self) -> None:
        paused = await self.execute(own_image_write=False, outcome='question')
        with self.Session() as db:
            db.get(Document, 1).current_html = '<p>用户修改后的正文</p>'
            db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.answer(paused['id'])
        self.assertEqual(error.exception.status_code, 409)
        with self.Session() as db:
            self.assertEqual(db.get(ChatUserQuestion, paused['id']).status, ChatUserQuestionStatus.WAITING)
            self.assertEqual(db.get(Document, 1).current_html, '<p>用户修改后的正文</p>')

    async def test_real_edit_before_question_is_rejected_before_publishing_pause(self) -> None:
        final = await self.execute(own_image_write=False, external_html='<p>外部修改</p>', outcome='question')
        self.assertEqual(final['run_status'], 'failed')
        with self.Session() as db:
            self.assertEqual(db.scalars(select(ChatUserQuestion)).all(), [])
            self.assertEqual(db.get(Document, 1).current_html, '<p>外部修改</p>')

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
