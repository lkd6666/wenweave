from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes import chat as chat_module
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_user_question import ChatUserQuestion, ChatUserQuestionStatus
from app.models.document import Document
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole


class PendingUserQuestionNotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _run(run_id: str, document_id: int, user_id: int, status: AgentRunStatus) -> AgentRun:
        return AgentRun(
            id=run_id,
            document_id=document_id,
            session_id=document_id,
            user_id=user_id,
            user_message_id=document_id,
            client_request_id=f"request-{run_id}",
            status=status,
            event_sequence=7,
        )

    @staticmethod
    def _question(
        question_id: str,
        run_id: str,
        document_id: int,
        user_id: int,
        created_at: datetime,
        status: ChatUserQuestionStatus = ChatUserQuestionStatus.WAITING,
    ) -> ChatUserQuestion:
        return ChatUserQuestion(
            id=question_id,
            run_id=run_id,
            document_id=document_id,
            session_id=document_id,
            user_id=user_id,
            model_id=1,
            tool_call_id=f"tool-{question_id}",
            status=status,
            question_json=json.dumps(
                {
                    "question": f"问题 {question_id}",
                    "options": [{"id": "option-1", "label": "方案一"}],
                },
                ensure_ascii=False,
            ),
            resume_messages_json="[]",
            completed_context_events_json="[]",
            execution_context_json="{}",
            timeline_json="{}",
            created_at=created_at,
        )

    def _seed_questions(self) -> None:
        db = self.session_factory()
        try:
            db.add_all(
                [
                    User(id=1, username="owner", display_name="Owner", password_hash="hash", role=UserRole.USER),
                    User(id=2, username="other", display_name="Other", password_hash="hash", role=UserRole.USER),
                    Document(id=1, owner_id=1, title="稍后的问题", current_html="", visibility_mode=VisibilityMode.ALL),
                    Document(id=2, owner_id=1, title="较早的问题", current_html="", visibility_mode=VisibilityMode.ALL),
                    Document(id=3, owner_id=1, title="已失去权限", current_html="", visibility_mode=VisibilityMode.RESTRICTED),
                ]
            )
            db.flush()
            db.add_all(
                [
                    self._run("run-later", 1, 1, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-earlier", 2, 1, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-private", 3, 1, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-other", 1, 2, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-running", 1, 1, AgentRunStatus.RUNNING),
                ]
            )
            db.flush()
            db.add_all(
                [
                    self._question("later", "run-later", 1, 1, datetime(2026, 8, 15, 2, tzinfo=timezone.utc)),
                    self._question("earlier", "run-earlier", 2, 1, datetime(2026, 8, 15, 1, tzinfo=timezone.utc)),
                    self._question("private", "run-private", 3, 1, datetime(2026, 8, 15, 0, tzinfo=timezone.utc)),
                    self._question("other", "run-other", 1, 2, datetime(2026, 8, 15, 0, tzinfo=timezone.utc)),
                    self._question("running", "run-running", 1, 1, datetime(2026, 8, 15, 0, tzinfo=timezone.utc)),
                ]
            )
            db.commit()
        finally:
            db.close()

    def test_snapshot_filters_by_user_access_and_run_state_then_orders_oldest_first(self) -> None:
        self._seed_questions()
        with patch.object(chat_module, "SessionLocal", self.session_factory):
            snapshot = chat_module._pending_user_question_snapshot(1)

        self.assertEqual([item["question"]["id"] for item in snapshot], ["earlier", "later"])
        self.assertEqual(snapshot[0]["document_title"], "较早的问题")
        self.assertEqual(snapshot[0]["question"]["event_sequence"], 7)
        self.assertTrue(snapshot[0]["created_at"].endswith("Z"))

    async def test_event_stream_emits_an_initial_complete_snapshot(self) -> None:
        self._seed_questions()
        with patch.object(chat_module, "SessionLocal", self.session_factory):
            stream = chat_module._pending_user_question_event_stream(1)
            event = await anext(stream)
            await stream.aclose()

        self.assertEqual(event["event"], "pending_questions")
        self.assertEqual([item["question"]["id"] for item in json.loads(event["data"])], ["earlier", "later"])

    def test_endpoint_uses_non_cacheable_sse_headers(self) -> None:
        response = chat_module.stream_pending_user_questions(current_user=SimpleNamespace(id=1))

        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(response.headers["x-accel-buffering"], "no")

