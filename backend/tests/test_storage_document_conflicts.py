import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes import storage
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.user import User, UserRole


class StorageDocumentConflictTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(id=1, username='admin', password_hash='x', role=UserRole.ADMIN)
        self.document = Document(id=1, owner_id=1, title='article', current_html='<img src="/old.png">')
        self.db.add_all([self.user, self.document])
        self.db.flush()
        self.db.add(ChatSession(id=1, document_id=1, title='chat'))
        self.db.flush()
        self.db.add(ChatMessage(id=1, document_id=1, session_id=1, role=MessageRole.USER, content='test'))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def repair(self, refresh):
        with (patch.object(storage, '_storage_if_configured', return_value=object()),
              patch.object(storage.oss_client, 'refresh_document_image_urls', side_effect=refresh)):
            return storage.repair_image_access(self.user, self.db)

    def start_run(self, run_status):
        self.db.add(AgentRun(id='run', document_id=1, session_id=1, user_id=1,
                             user_message_id=1, client_request_id='run', status=run_status))
        self.db.commit()

    def test_link_repair_skips_every_active_agent_state(self):
        self.start_run(AgentRunStatus.PENDING)
        for run_status in (AgentRunStatus.PENDING, AgentRunStatus.RUNNING,
                           AgentRunStatus.WAITING_FOR_INPUT, AgentRunStatus.CANCELLING):
            self.db.get(AgentRun, 'run').status = run_status
            self.db.commit()
            result = self.repair(lambda *_args: self.fail('active document must be skipped'))
            self.assertEqual(result.repaired_count, 0)
            self.assertIn('跳过 1', result.message)
            self.assertEqual(self.db.get(Document, 1).current_html, '<img src="/old.png">')

    def test_link_repair_keeps_edits_committed_during_refresh(self):
        def refresh(*_args):
            with Session(self.engine) as other:
                other.get(Document, 1).current_html = '<p>newer manual edit</p>'
                other.commit()
            return ['<img src="/repaired.png">'], 1

        result = self.repair(refresh)
        self.assertEqual(result.repaired_count, 0)
        self.assertEqual(self.db.get(Document, 1).current_html, '<p>newer manual edit</p>')

    def test_idle_document_link_repair_still_updates_html(self):
        result = self.repair(lambda *_args: (['<img src="/repaired.png">'], 1))
        self.assertEqual(result.repaired_count, 1)
        self.assertEqual(self.db.get(Document, 1).current_html, '<img src="/repaired.png">')

    def test_link_repair_rechecks_a_run_started_during_refresh(self):
        def refresh(*_args):
            self.start_run(AgentRunStatus.RUNNING)
            return ['<img src="/repaired.png">'], 1

        result = self.repair(refresh)
        self.assertEqual(result.repaired_count, 0)
        self.assertEqual(self.db.get(Document, 1).current_html, '<img src="/old.png">')
