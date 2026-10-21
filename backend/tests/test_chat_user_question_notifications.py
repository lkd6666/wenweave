from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes import chat as chat_module
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_user_question import ChatUserQuestion, ChatUserQuestionStatus
from app.models.chat_message import ChatMessage, MessageRole
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.document_visibility import VisibilityMode, document_group_visible_users
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
                    DocumentGroup(id=10, owner_id=1, name="仅其他用户可见", visibility_mode=VisibilityMode.RESTRICTED),
                    Document(id=1, owner_id=1, title="稍后的问题", current_html="", visibility_mode=VisibilityMode.ALL),
                    Document(id=2, owner_id=1, title="较早的问题", current_html="", visibility_mode=VisibilityMode.ALL),
                    Document(id=3, owner_id=1, title="已失去权限", current_html="", visibility_mode=VisibilityMode.RESTRICTED),
                    Document(id=4, owner_id=1, group_id=10, title="其他用户分组", current_html="", visibility_mode=VisibilityMode.ALL),
                ]
            )
            db.flush()
            db.execute(document_group_visible_users.insert().values(document_group_id=10, user_id=2))
            db.add_all(
                [
                    self._run("run-later", 1, 1, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-earlier", 2, 1, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-private", 3, 1, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-other", 1, 2, AgentRunStatus.WAITING_FOR_INPUT),
                    self._run("run-running", 1, 1, AgentRunStatus.RUNNING),
                    self._run("run-foreign-group", 4, 1, AgentRunStatus.WAITING_FOR_INPUT),
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
                    self._question("foreign-group", "run-foreign-group", 4, 1, datetime(2026, 8, 15, 0, tzinfo=timezone.utc)),
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

    def test_multiple_users_are_permission_filtered_in_one_select(self) -> None:
        self._seed_questions()
        selects: list[str] = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            with patch.object(chat_module, "SessionLocal", self.session_factory):
                snapshots = chat_module._pending_user_question_snapshots([1, 2])
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual([item["question"]["id"] for item in snapshots[1]], ["earlier", "later"])
        self.assertEqual([item["question"]["id"] for item in snapshots[2]], ["other"])
        self.assertEqual(len(selects), 1)

    async def test_event_stream_emits_an_initial_complete_snapshot(self) -> None:
        self._seed_questions()
        with patch.object(chat_module, "SessionLocal", self.session_factory):
            stream = chat_module._pending_user_question_event_stream(1)
            event = await anext(stream)
            await stream.aclose()

        self.assertEqual(event["event"], "pending_questions")
        self.assertEqual([item["question"]["id"] for item in json.loads(event["data"])], ["earlier", "later"])

    async def test_ten_tabs_share_polling_and_last_unsubscribe_stops_it(self) -> None:
        broker = chat_module._PendingQuestionBroker()
        calls: list[list[int]] = []

        def snapshots(user_ids: list[int]) -> dict[int, list[dict]]:
            calls.append(list(user_ids))
            return {user_id: [] for user_id in user_ids}

        streams = [broker.subscribe(1) for _ in range(10)]
        with (
            patch.object(chat_module, "_pending_user_question_snapshots", side_effect=snapshots),
            patch.object(chat_module, "USER_QUESTION_SNAPSHOT_INTERVAL_SECONDS", 0.01),
        ):
            initial = await asyncio.gather(*(anext(stream) for stream in streams))
            self.assertTrue(all(item == "[]" for item in initial))
            await asyncio.sleep(0.025)
            # The old per-connection loop would execute roughly 30 queries in
            # this window. One broker pass serves all ten local tabs.
            self.assertLessEqual(len(calls), 4)
            self.assertTrue(all(call == [1] for call in calls))
            await asyncio.gather(*(stream.aclose() for stream in streams))
            stopped_at = len(calls)
            await asyncio.sleep(0.025)
            self.assertEqual(len(calls), stopped_at)

    def test_endpoint_uses_non_cacheable_sse_headers(self) -> None:
        response = chat_module.stream_pending_user_questions(current_user=SimpleNamespace(id=1))

        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(response.headers["x-accel-buffering"], "no")

    async def test_stopping_a_waiting_question_finishes_without_compliance_and_is_idempotent(self) -> None:
        self._seed_questions()
        manager = SimpleNamespace(publish=AsyncMock(), mark_terminal=AsyncMock())
        timer = asyncio.create_task(asyncio.sleep(60))
        chat_module._user_question_timeout_tasks["later"] = timer
        try:
            with (
                self.session_factory() as db,
                patch.object(chat_module, "agent_run_manager", manager),
                patch("app.services.wechat_compliance.get_official_compliance_engine", side_effect=AssertionError("Unexpected automatic check")) as checker,
            ):
                user = db.get(User, 1)
                result = await chat_module.cancel_chat_run(1, "run-later", user, db)
                repeated = await chat_module.cancel_chat_run(1, "run-later", user, db)

                self.assertEqual(result.status, AgentRunStatus.CANCELLED)
                self.assertEqual(repeated.assistant_message_id, result.assistant_message_id)
                self.assertEqual(db.get(ChatUserQuestion, "later").status, ChatUserQuestionStatus.CANCELLED)
                self.assertEqual(db.query(ChatMessage).filter(ChatMessage.role == MessageRole.ASSISTANT).count(), 1)
                checker.assert_not_called()
            await asyncio.sleep(0)
            self.assertTrue(timer.cancelled())
            manager.publish.assert_awaited_once()
            self.assertIsNone(manager.publish.call_args.args[2]["compliance"])
            manager.mark_terminal.assert_awaited_once_with("run-later", "cancelled")
        finally:
            chat_module.cancel_user_question_timeout("later")
            if not timer.done():
                timer.cancel()
