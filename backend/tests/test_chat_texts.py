import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import app.models
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.api.routes import chat
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_context_event import ChatContextEvent
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.user import User, UserRole
from app.schemas.chat import ChatMessageRead, ChatSendRequest
from app.services import chat_texts as texts
from app.services.token_budget import estimate_tokens
from app.services.chat_agent import HtmlEditSession, run_agent_loop
from app.services.source_agent import create_source_workspace
from app.services.tool_output_store import ToolOutputStore
from tests.test_agent_loop_end_to_end import ScriptedChatModel


class ChatTextTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(id=1, username='test', password_hash='unused', role=UserRole.ADMIN)
        self.session = ChatSession(document_id=1, title='Chat')
        provider = AIProvider(id=1, name='Test', provider_type=ProviderType.OPENAI_COMPATIBLE, base_url='https://example.invalid')
        self.model = AIModel(provider=provider, model_name='test', display_name='test', context_window_tokens=32768,
            context_compaction_threshold_tokens=24000, max_output_tokens=1000, tool_result_max_tokens=1000)
        self.db.add_all([self.user, Document(id=1, owner_id=1, title='Test', current_html='<p>Article</p>'), self.session, self.model])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create(self, content='正文🙂\n第二行'):
        return texts.create_text(self.db, document_id=1, session_id=self.session.id, uploader_id=1,
            filename='资料.txt', data=content.encode('utf-8'))

    def bind(self, item):
        message = ChatMessage(document_id=1, session_id=self.session.id, role=MessageRole.USER, content='请核对资料')
        self.db.add(message)
        self.db.flush()
        texts.bind_texts(self.db, [item], message.id, 1)
        return message

    def test_unicode_pagination_is_lossless_and_counts_json_budget(self):
        item = self.create('中文🙂abcdef' * 900)
        content, cursor = '', 0
        while True:
            page = texts.read_text(item, start=cursor, budget=400)
            self.assertLessEqual(estimate_tokens(json.dumps(page, ensure_ascii=False, separators=(',', ':'))), 400)
            content += page['content']
            if page['next_cursor'] is None:
                break
            self.assertGreater(page['next_cursor'], cursor)
            cursor = page['next_cursor']
        self.assertEqual(content, item.content)
        with self.assertRaises(texts.WorkspaceError):
            texts.read_text(item, start=-1)

    def test_browser_pages_continue_past_the_first_8000_characters(self):
        item = self.create('a' * 18000)
        one = chat.view_chat_text(1, item.id, 0, self.user, self.db)
        self.assertEqual(one['next_cursor'], 8000)
        two = chat.view_chat_text(1, item.id, one['next_cursor'], self.user, self.db)
        three = chat.view_chat_text(1, item.id, two['next_cursor'], self.user, self.db)
        self.assertIsNone(three['next_cursor'])
        self.assertEqual(one['content'] + two['content'] + three['content'], item.content)

    def test_search_is_literal_and_bounded(self):
        item = self.create(('noise ' * 300 + 'KEY.*WORD\n') * 20)
        result = texts.search_text(item, 'KEY.*WORD', limit=2, budget=600)
        self.assertEqual(len(result['matches']), 2)
        self.assertIsNotNone(result['next_cursor'])
        self.assertLessEqual(estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(',', ':'))), 600)
        with self.assertRaises(texts.WorkspaceError):
            texts.search_text(item, '')

    def test_validation_and_quotas(self):
        for data in (b'', b'\x00binary', b'\x01', b'\xff', b'a' * (texts.MAX_TEXT_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(texts.WorkspaceError):
                texts.create_text(self.db, document_id=1, session_id=self.session.id, uploader_id=1, filename='x', data=data)
        for _ in range(32):
            self.create()
        with self.assertRaises(texts.WorkspaceError):
            self.create()
        with self.assertRaises(texts.WorkspaceError):
            texts.select_for_send(self.db, 1, self.session.id, 1, ['x'] * 9)

    def test_permissions_active_context_and_immutable_resend(self):
        item = self.create()
        for doc, session, user in ((2, self.session.id, 1), (1, self.session.id + 1, 1), (1, self.session.id, 2)):
            with self.assertRaises(texts.WorkspaceError):
                texts.select_for_send(self.db, doc, session, user, [item.id])
        with self.assertRaises(texts.WorkspaceError):
            texts.authorized_text(self.db, item.id, 1, self.session.id)
        message = self.bind(item)
        self.assertEqual(texts.authorized_text(self.db, item.id, 1, self.session.id).id, item.id)
        with self.assertRaises(HTTPException):
            chat.delete_chat_text(1, item.id, self.user, self.db)
        clone = texts.bind_texts(self.db, [item], message.id + 1, 1)[0]
        self.assertNotEqual(clone.id, item.id)
        self.assertEqual(item.message_id, message.id)
        self.assertEqual(clone.content, item.content)
        for attr, value in [('is_superseded', True), ('history_archive_id', 2)]:
            setattr(message, attr, value)
            with self.assertRaises(texts.WorkspaceError):
                texts.authorized_text(self.db, item.id, 1, self.session.id)
            setattr(message, attr, False if attr == 'is_superseded' else None)
        self.session.context_start_message_id = message.id
        with self.assertRaises(texts.WorkspaceError):
            texts.authorized_text(self.db, item.id, 1, self.session.id)
        self.session.context_start_message_id = 0
        self.session.is_archived = True
        with self.assertRaises(texts.WorkspaceError):
            texts.authorized_text(self.db, item.id, 1, self.session.id)

    def test_history_serialization_does_not_load_body(self):
        marker = 'PRIVATE_ATTACHMENT_BODY_123'
        item = self.create(marker * 2000)
        message = self.bind(item)
        self.db.commit()
        self.db.expire_all()
        row = self.db.get(ChatMessage, message.id)
        attachment = row.text_attachments[0]
        self.assertIn('content', inspect(attachment).unloaded)
        self.assertNotIn(marker, ChatMessageRead.model_validate(row).model_dump_json())
        reference = texts.reference_text([attachment])
        self.assertNotIn(marker, reference)
        self.assertIn('search_text_attachment', reference)
        self.assertIn('content', inspect(attachment).unloaded)

    def test_old_client_long_input_is_externalized_before_ledger_and_model(self):
        marker = 'PRIVATE_LARGE_INPUT_' * 5000
        self.db.commit()

        async def send():
            result = await chat.start_chat_run(1, ChatSendRequest(model_id=self.model.id, session_id=self.session.id,
                message=marker, client_request_id='long-input-test'), self.user, self.db)
            await asyncio.sleep(0)
            return result

        with (patch.object(chat, 'build_chat_model', return_value=(None, None)),
              patch.object(chat, 'build_compaction_model', return_value=None),
              patch.object(chat, '_require_agent_capacity'),
              patch.object(chat, 'agent_run_manager', lease_seconds=120, worker_id='text-test'),
              patch.object(chat, '_execute_agent_run', new_callable=AsyncMock) as execute):
            result = asyncio.run(send())
        message = self.db.get(ChatMessage, result.user_message_id)
        self.assertNotIn('PRIVATE_LARGE_INPUT_', message.content)
        self.assertEqual(message.text_attachments[0].content, marker)
        self.assertNotIn('PRIVATE_LARGE_INPUT_', execute.call_args.kwargs['user_message'])
        self.assertIn(message.text_attachments[0].id, execute.call_args.kwargs['user_message'])
        for event in self.db.query(ChatContextEvent).all():
            self.assertNotIn('PRIVATE_LARGE_INPUT_', event.payload_json)

    def test_model_tools_read_authorized_bounded_fragments_on_v1_and_v2(self):
        item = self.create('资料开始\n' + '普通内容🙂' * 8000 + '\n检索目标')
        self.bind(item)
        self.db.commit()
        for protocol in ('v1', 'v2'):
            session = HtmlEditSession('<p>Article</p>', tool_result_max_tokens=600)
            model = ScriptedChatModel(script=[{'tool': ('search_text_attachment', {'attachment_id': item.id, 'query': '检索目标'})},
                {'tool': ('read_text_attachment', {'attachment_id': item.id, 'start': 0})},
                {'tool': ('read_text_attachment', {'attachment_id': 'wrong-session'})}, {'text': '完成'}], seen_messages=[], seen_message_counts=[])

            async def go():
                return [event async for event in run_agent_loop(model, 'Test', session.html, '核对附件' + texts.reference_text([item]),
                    create_source_workspace(session).map_payload(), None, [], session=session, tool_protocol=protocol,
                    tool_output_store=ToolOutputStore(document_id=1, session_id=self.session.id, run_id='test-run'))]

            with patch('app.services.chat_agent.SessionLocal', side_effect=lambda: Session(self.engine)):
                events = asyncio.run(go())
            values = [event['data']['model_input']['content'] for event in events if event['event'] == 'tool_result']
            self.assertEqual(len(values), 3)
            self.assertEqual(json.loads(values[0])['match_count'], 1)
            self.assertIsNotNone(json.loads(values[1])['next_cursor'])
            self.assertFalse(json.loads(values[2])['ok'])
            self.assertTrue(all(estimate_tokens(value) <= 600 for value in values))
            self.assertNotIn(item.content, str(model.seen_messages[0]))
