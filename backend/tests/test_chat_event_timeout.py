import asyncio
import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import anyio
from langchain_core.messages import AIMessageChunk
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - register referenced tables for the isolated database.
import app.api.routes.chat as chat_module
import app.bootstrap as bootstrap_module
from app.db.base import Base
from app.api.routes.chat import _agent_execution_error_message, _commit_waiting_user_question, _force_stuck_cancellation, _has_external_document_conflict, _is_context_limit_error, _is_retryable_db_disconnect, _iterate_agent_events_with_timeout, _preserve_retried_tool_previews, _restart_failure_events, _settle_terminal_timeline, _settle_user_question_timeline, _unresolved_edit_failure
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_run_event import AgentRunEvent
from app.models.chat_user_question import ChatUserQuestion, ChatUserQuestionStatus
from app.models.chat_message import ChatMessage
from app.models.document import Document
from app.models.user import User
from app.schemas.chat import ChatMessageRead, ChatUserQuestionAnswerRequest
from app.services.agent_run_manager import AgentRunManager
from app.services.chat_agent import ModelStreamCleanupError, ModelStreamTimeoutError, _iterate_model_stream_with_idle_limits


class AgentEventTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def test_live_run_timeline_returns_a_snapshot_at_the_durable_cursor(self) -> None:
        engine = create_engine("sqlite://")
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        try:
            with session_factory() as db:
                run = AgentRun(
                    id="run-live-snapshot",
                    document_id=1,
                    session_id=1,
                    user_id=1,
                    user_message_id=1,
                    client_request_id="request-live-snapshot",
                    status=AgentRunStatus.RUNNING,
                    event_sequence=3,
                )
                db.add(run)
                db.add_all([
                    AgentRunEvent(
                        run_id=run.id,
                        sequence=1,
                        event="reasoning_delta",
                        payload_json='{"text":"先检查标题。"}',
                    ),
                    AgentRunEvent(
                        run_id=run.id,
                        sequence=2,
                        event="tool_call",
                        payload_json='{"id":"tool-1","name":"read_blocks","arguments":{}}',
                    ),
                    AgentRunEvent(
                        run_id=run.id,
                        sequence=3,
                        event="text_delta",
                        payload_json='{"text":"正在调整标题层级"}',
                    ),
                    AgentRunEvent(
                        run_id=run.id,
                        sequence=4,
                        event="text_delta",
                        payload_json='{"text":"不应进入快照"}',
                    ),
                ])
                db.commit()

                timeline = chat_module._live_run_timeline(db, run)
                payload = chat_module._run_read(run, timeline=timeline)

            self.assertIsNotNone(timeline)
            assert timeline is not None
            self.assertEqual(timeline.reasoning.content, "先检查标题。")
            self.assertEqual(timeline.turn_blocks[-1].content, "正在调整标题层级")
            self.assertEqual(payload.event_sequence, 3)
        finally:
            engine.dispose()

    def test_persisted_waiting_question_is_readable_after_session_closes(self) -> None:
        engine = create_engine("sqlite://")
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        question = ChatUserQuestion(
            id="question-1",
            run_id="run-1",
            document_id=1,
            session_id=1,
            user_id=1,
            model_id=1,
            tool_call_id="call-1",
            status=ChatUserQuestionStatus.WAITING,
            question_json='{"question": "请选择"}',
            resume_messages_json="[]",
            completed_context_events_json="[]",
            execution_context_json="{}",
            timeline_json="{}",
        )
        try:
            db = session_factory()
            db.add(question)
            db.commit()
            db.refresh(question)
            db.expunge(question)
            db.close()

            self.assertEqual(question.status, ChatUserQuestionStatus.WAITING)
            self.assertEqual(question.question["question"], "请选择")
        finally:
            engine.dispose()

    def test_waiting_question_and_sse_event_commit_atomically_with_json_deadline(self) -> None:
        engine = create_engine("sqlite://")
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        now = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
        try:
            with session_factory() as db:
                db.add(
                    AgentRun(
                        id="run-question-atomic",
                        document_id=1,
                        session_id=1,
                        user_id=1,
                        user_message_id=1,
                        client_request_id="request-question-atomic",
                        status=AgentRunStatus.RUNNING,
                        owner_id="worker-1",
                        event_sequence=2,
                    )
                )
                db.add(
                    AgentRunEvent(
                        run_id="run-question-atomic",
                        sequence=3,
                        event="tool_call",
                        payload_json='{"id":"call-1","name":"ask_user"}',
                    )
                )
                db.commit()

            question = ChatUserQuestion(
                id="question-atomic",
                run_id="run-question-atomic",
                document_id=1,
                session_id=1,
                user_id=1,
                model_id=1,
                tool_call_id="call-1",
                status=ChatUserQuestionStatus.WAITING,
                question_json='{"question":"请选择","options":[]}',
                resume_messages_json='[{"type":"ai"}]',
                completed_context_events_json="[]",
                execution_context_json="{}",
                timeline_json="{}",
                last_activity_at=now,
                timeout_at=now + timedelta(minutes=2),
            )
            with session_factory() as db:
                persisted, sequence, payload, occurred_at = _commit_waiting_user_question(
                    db,
                    "run-question-atomic",
                    question,
                    now=now,
                )

            with session_factory() as db:
                run = db.get(AgentRun, "run-question-atomic")
                event = (
                    db.query(AgentRunEvent)
                    .filter(AgentRunEvent.run_id == "run-question-atomic")
                    .order_by(AgentRunEvent.sequence.desc())
                    .first()
                )

            assert run is not None and event is not None
            self.assertEqual(persisted.id, "question-atomic")
            self.assertEqual(sequence, 4)
            self.assertEqual(occurred_at, now)
            self.assertEqual(run.status, AgentRunStatus.WAITING_FOR_INPUT)
            self.assertEqual(run.event_sequence, 4)
            self.assertEqual(run.owner_id, "")
            self.assertEqual(event.event, "user_question")
            self.assertEqual(json.loads(event.payload_json), payload)
            self.assertIsInstance(payload["timeout_at"], str)
            json.dumps(payload)
        finally:
            engine.dispose()

    def test_question_read_serializes_a_naive_mysql_deadline_as_utc(self) -> None:
        question = SimpleNamespace(
            id="question-utc",
            run_id="run-utc",
            status=ChatUserQuestionStatus.WAITING,
            question={"question": "请选择", "options": []},
            timeline_json="{}",
            timeout_at=datetime(2026, 7, 29, 16, 0, 0),
            last_activity_at=None,
            created_at=datetime(2026, 7, 29, 15, 58, 0),
        )

        payload = chat_module._question_read(question)

        self.assertIsNotNone(payload)
        self.assertEqual(payload.timeout_at, datetime(2026, 7, 29, 16, 0, 0, tzinfo=timezone.utc))

    def test_run_can_persist_multiple_questions_with_distinct_tool_calls(self) -> None:
        engine = create_engine("sqlite://")
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

        def question(question_id: str, tool_call_id: str) -> ChatUserQuestion:
            return ChatUserQuestion(
                id=question_id,
                run_id="run-1",
                document_id=1,
                session_id=1,
                user_id=1,
                model_id=1,
                tool_call_id=tool_call_id,
                status=ChatUserQuestionStatus.ANSWERED,
                question_json="{}",
                resume_messages_json="[]",
                completed_context_events_json="[]",
                execution_context_json="{}",
                timeline_json="{}",
            )

        try:
            db = session_factory()
            db.add_all([question("question-1", "call-1"), question("question-2", "call-2")])
            db.commit()
            self.assertEqual(db.query(ChatUserQuestion).filter_by(run_id="run-1").count(), 2)

            db.add(question("question-3", "call-2"))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
            db.close()
        finally:
            engine.dispose()

    def test_sqlite_migrates_legacy_unique_run_question_table(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE chat_user_questions")
                connection.exec_driver_sql(
                    """
                    CREATE TABLE chat_user_questions (
                        id VARCHAR(36) PRIMARY KEY,
                        run_id VARCHAR(36) NOT NULL,
                        document_id INTEGER NOT NULL,
                        session_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        model_id INTEGER NOT NULL,
                        tool_call_id VARCHAR(128) NOT NULL,
                        status VARCHAR(16) NOT NULL,
                        question_json TEXT NOT NULL DEFAULT '{}',
                        resume_messages_json TEXT NOT NULL DEFAULT '[]',
                        completed_context_events_json TEXT NOT NULL DEFAULT '[]',
                        execution_context_json TEXT NOT NULL DEFAULT '{}',
                        timeline_json TEXT NOT NULL DEFAULT '{}',
                        answer_json TEXT NOT NULL DEFAULT '{}',
                        answer_client_request_id VARCHAR(96),
                        last_activity_at DATETIME,
                        timeout_at DATETIME,
                        answered_at DATETIME,
                        created_at DATETIME,
                        CONSTRAINT uq_chat_user_questions_run UNIQUE (run_id),
                        CONSTRAINT uq_chat_user_questions_answer_request UNIQUE (answer_client_request_id)
                    )
                    """
                )
            with patch.object(bootstrap_module, "engine", engine):
                bootstrap_module.migrate_schema()

            constraints = {
                item["name"]: item["column_names"]
                for item in inspect(engine).get_unique_constraints("chat_user_questions")
            }
            self.assertNotIn("uq_chat_user_questions_run", constraints)
            self.assertEqual(constraints["uq_chat_user_questions_run_call"], ["run_id", "tool_call_id"])
        finally:
            engine.dispose()

    def test_answering_question_settles_its_exact_timeline_tool(self) -> None:
        tool_calls = [
            {"id": "call-1", "name": "ask_user", "status": "waiting", "preparing": False},
            {"id": "call-2", "name": "ask_user", "status": "waiting", "preparing": False},
        ]
        turn_blocks = [
            {"type": "tool", "tool": {"id": "call-1", "name": "ask_user", "status": "waiting"}},
            {"type": "tool", "tool": {"id": "call-2", "name": "ask_user", "status": "waiting"}},
        ]

        self.assertEqual(_settle_user_question_timeline(tool_calls, turn_blocks, "call-1"), "call-1")
        self.assertEqual(tool_calls[0]["status"], "success")
        self.assertEqual(turn_blocks[0]["tool"]["status"], "success")
        self.assertEqual(tool_calls[0]["model_input"]["state"], "not_sent")
        self.assertEqual(turn_blocks[0]["tool"]["model_input"]["state"], "not_sent")
        self.assertEqual(tool_calls[1]["status"], "waiting")
        self.assertEqual(turn_blocks[1]["tool"]["status"], "waiting")

    def test_answering_question_records_the_exact_provider_visible_answer(self) -> None:
        tool_calls = [{"id": "call-answer", "name": "ask_user", "status": "waiting", "preparing": False}]
        turn_blocks = [{"type": "tool", "tool": {"id": "call-answer", "name": "ask_user", "status": "waiting"}}]
        provider_content = '{"action":"selected","selected_options":[{"id":"option-1"}]}'

        self.assertEqual(
            _settle_user_question_timeline(
                tool_calls,
                turn_blocks,
                "call-answer",
                {"action": "selected"},
                model_input_content=provider_content,
            ),
            "call-answer",
        )
        self.assertEqual(tool_calls[0]["model_input"], {
            "state": "available",
            "content": provider_content,
            "truncated": False,
        })
        self.assertEqual(turn_blocks[0]["tool"]["model_input"], tool_calls[0]["model_input"])

    def test_model_retry_keeps_unexecuted_patch_visible_as_interrupted(self) -> None:
        checkpoint_tools = [{"id": "read-1", "name": "read_blocks", "status": "success"}]
        checkpoint_blocks = [{"id": "block-read-1", "type": "tool", "state": "done", "content": "", "tool": checkpoint_tools[0]}]
        current_patch = {
            "id": "patch-1",
            "name": "apply_html_patch",
            "status": "running",
            "preparing": True,
            "argument_tokens": 16393,
        }
        current_tools = [*checkpoint_tools, current_patch]
        current_blocks = [*checkpoint_blocks, {"id": "block-patch-1", "type": "tool", "state": "done", "content": "", "tool": current_patch}]

        tools, blocks, interrupted_ids = _preserve_retried_tool_previews(
            checkpoint_tools,
            checkpoint_blocks,
            current_tools,
            current_blocks,
            {"attempt": 2, "reason": "stream_progress_idle_timeout"},
        )

        self.assertEqual(interrupted_ids, ["patch-1:retry-2"])
        self.assertEqual(tools[-1]["status"], "interrupted")
        self.assertEqual(tools[-1]["argument_tokens"], 16393)
        self.assertIn("尚未执行", tools[-1]["result"])
        self.assertEqual(blocks[-1]["tool"]["id"], "patch-1:retry-2")

    def test_interrupted_tool_preview_is_readable_from_chat_schema(self) -> None:
        message = ChatMessageRead.model_validate(
            {
                "id": 1,
                "role": "assistant",
                "content": "",
                "created_at": datetime.now(timezone.utc),
                "tool_calls": [
                    {
                        "id": "patch-1:retry-2",
                        "name": "apply_html_patch",
                        "status": "interrupted",
                        "preparing": False,
                        "result": "本次工具参数生成被模型重试中断，尚未执行任何修改。",
                    }
                ],
                "turn_blocks": [
                    {
                        "id": "block-patch-1:retry-2",
                        "type": "tool",
                        "state": "done",
                        "tool": {
                            "id": "patch-1:retry-2",
                            "name": "apply_html_patch",
                            "status": "interrupted",
                        },
                    }
                ],
            }
        )

        self.assertEqual(message.tool_calls[0].status, "interrupted")
        self.assertEqual(message.turn_blocks[0].tool.status, "interrupted")

    def test_settling_a_legacy_timeline_backfills_missing_block_content(self) -> None:
        tool_calls = [{"id": "call-1", "name": "ask_user", "status": "success"}]
        turn_blocks = [{"id": "block-call-1", "type": "tool", "state": "done", "tool": tool_calls[0]}]

        self.assertTrue(chat_module._settle_terminal_timeline(tool_calls, turn_blocks))
        self.assertEqual(turn_blocks[0]["content"], "")

    def test_answering_legacy_question_settles_the_transient_timeline_tool(self) -> None:
        tool_calls = [{"id": "tool-run-0-0", "name": "ask_user", "status": "running", "preparing": False}]
        turn_blocks = [{"type": "tool", "tool": {"id": "tool-run-0-0", "name": "ask_user", "status": "running"}}]

        self.assertEqual(_settle_user_question_timeline(tool_calls, turn_blocks, "call-provider-1"), "tool-run-0-0")
        self.assertEqual(tool_calls[0]["status"], "success")
        self.assertEqual(turn_blocks[0]["tool"]["status"], "success")

    def test_timed_out_question_timeline_never_claims_a_user_answer(self) -> None:
        tool_calls = [{"id": "call-timeout", "name": "ask_user", "status": "waiting", "preparing": False}]
        turn_blocks = [{"type": "tool", "tool": {"id": "call-timeout", "name": "ask_user", "status": "waiting"}}]

        self.assertEqual(
            _settle_user_question_timeline(
                tool_calls,
                turn_blocks,
                "call-timeout",
                {"action": "no_response"},
            ),
            "call-timeout",
        )
        self.assertIn("用户在规定时间内未回复", tool_calls[0]["result"])
        self.assertEqual(tool_calls[0]["activity"]["summary"], "用户未回复，已自动继续")

    def test_cancelled_question_timeline_is_not_reported_as_a_tool_failure(self) -> None:
        tool_calls = [{"id": "call-cancel", "name": "ask_user", "status": "waiting", "preparing": False}]
        turn_blocks = [{"type": "tool", "tool": {"id": "call-cancel", "name": "ask_user", "status": "waiting"}}]

        self.assertEqual(
            _settle_user_question_timeline(
                tool_calls,
                turn_blocks,
                "call-cancel",
                {"action": "cancelled"},
            ),
            "call-cancel",
        )
        self.assertEqual(tool_calls[0]["status"], "success")
        self.assertEqual(tool_calls[0]["activity"]["summary"], "本轮已停止")

    def test_answer_request_rejects_conflicting_forms_before_resuming_a_run(self) -> None:
        valid = ChatUserQuestionAnswerRequest(
            action="select",
            option_ids=[" option_1 ", "option_1"],
            client_request_id="answer-request-1",
        )
        self.assertEqual(valid.option_ids, ["option_1"])

        invalid_payloads = [
            {"action": "select", "option_ids": [], "client_request_id": "answer-request-2"},
            {"action": "custom", "option_ids": ["option_1"], "custom_requirement": "改成紧凑", "client_request_id": "answer-request-3"},
            {"action": "skip", "custom_requirement": "仍然回答", "client_request_id": "answer-request-4"},
            {"action": "timeout", "option_ids": ["option_1"], "client_request_id": "answer-request-5"},
        ]
        for payload in invalid_payloads:
            with self.assertRaises(ValidationError):
                ChatUserQuestionAnswerRequest(**payload)

    def test_replayed_question_event_is_hidden_after_its_answer_was_accepted(self) -> None:
        answered_question = SimpleNamespace(
            run_id="run-1",
            status=ChatUserQuestionStatus.ANSWERED,
        )
        waiting_run = SimpleNamespace(status=AgentRunStatus.WAITING_FOR_INPUT)

        class FakeSession:
            def rollback(self):
                pass

            def get(self, model, _identifier):
                return answered_question if model is ChatUserQuestion else waiting_run

            def close(self) -> None:
                pass

        with patch.object(chat_module, "SessionLocal", return_value=FakeSession()):
            self.assertFalse(chat_module._is_current_waiting_question_event("run-1", {"id": "question-1"}))

        answered_question.status = ChatUserQuestionStatus.WAITING
        with patch.object(chat_module, "SessionLocal", return_value=FakeSession()):
            self.assertTrue(chat_module._is_current_waiting_question_event("run-1", {"id": "question-1"}))

    def test_legacy_timeline_repair_restores_each_answered_question(self) -> None:
        tool_calls = [{"id": "tool-0-0", "name": "get_document_map", "status": "success"}]
        turn_blocks = [
            {"id": "thought-1", "type": "thought", "state": "done", "content": "先确认偏好"},
            {"id": "block-tool-0-0", "type": "tool", "state": "done", "tool": {"id": "tool-0-0", "name": "ask_user", "status": "running"}},
            {"id": "block-tool-1-0", "type": "tool", "state": "done", "tool": {"id": "tool-1-0", "name": "search_html", "status": "success"}},
        ]

        changed = bootstrap_module._repair_answered_user_question_timeline(
            tool_calls, turn_blocks, ["call-question-1", "call-question-2"]
        )

        self.assertTrue(changed)
        repaired_tools = [block["tool"] for block in turn_blocks if block.get("type") == "tool"]
        self.assertEqual([tool["id"] for tool in repaired_tools[:2]], ["call-question-1", "call-question-2"])
        self.assertTrue(all(tool["status"] == "success" for tool in repaired_tools[:2]))
        self.assertEqual([tool["id"] for tool in tool_calls[:2]], ["call-question-1", "call-question-2"])

    def test_agent_start_rate_limit_uses_the_database_clock(self) -> None:
        database_now = datetime(2026, 7, 29, 18, 40, 0)

        class FakeSession:
            def rollback(self):
                pass

            def query(self, _expression):
                return SimpleNamespace(scalar=lambda: database_now)

        self.assertEqual(
            chat_module._agent_start_cutoff(FakeSession()),
            datetime(2026, 7, 29, 18, 39, 0),
        )

    async def test_due_user_question_timeout_retries_after_an_activity_race(self) -> None:
        """A timer that wakes during activity must use the refreshed deadline."""
        resume = AsyncMock(side_effect=[False])
        sleep = AsyncMock()
        with (
            patch.object(chat_module, "_user_question_timeout_delay", side_effect=[0.0, 0.001, None]),
            patch.object(chat_module, "_auto_answer_timed_out_user_question", resume),
            patch.object(chat_module.asyncio, "sleep", sleep),
        ):
            await chat_module._wait_for_user_question_timeout("question-1")

        resume.assert_awaited_once_with("question-1")
        sleep.assert_any_await(chat_module.USER_QUESTION_TIMEOUT_RETRY_DELAY_SECONDS)

    async def test_resolving_a_question_cancels_its_local_timeout_task(self) -> None:
        task = asyncio.create_task(asyncio.sleep(60))
        chat_module._user_question_timeout_tasks["question-cancel"] = task
        try:
            chat_module.cancel_user_question_timeout("question-cancel")
            await asyncio.sleep(0)
            self.assertTrue(task.cancelled())
            self.assertNotIn("question-cancel", chat_module._user_question_timeout_tasks)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_due_user_question_timeout_uses_the_internal_timeout_answer(self) -> None:
        question = SimpleNamespace(
            id="question-1",
            document_id=3,
            run_id="run-1",
            user_id=7,
            status=ChatUserQuestionStatus.WAITING,
            timeout_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            last_activity_at=None,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        )
        owner = SimpleNamespace(id=7)
        run = SimpleNamespace(status=AgentRunStatus.WAITING_FOR_INPUT)

        class FakeQuery:
            def filter(self, *_args):
                return self

            def populate_existing(self):
                return self

            def with_for_update(self):
                return self

            def one_or_none(self):
                return question

        class FakeSession:
            def rollback(self):
                pass

            committed = False

            def query(self, _model):
                return FakeQuery()

            def get(self, model, _identifier):
                if model is ChatUserQuestion:
                    return question
                if model is AgentRun:
                    return run
                if model is User:
                    return owner
                return None

            def commit(self) -> None:
                self.committed = True

            def close(self) -> None:
                pass

        resume = AsyncMock()
        with (
            patch.object(chat_module, "SessionLocal", return_value=FakeSession()),
            patch.object(chat_module, "answer_chat_user_question", resume),
        ):
            completed = await chat_module._auto_answer_timed_out_user_question(question.id)

        self.assertTrue(completed)
        resume.assert_awaited_once()
        payload = resume.await_args.args[3]
        self.assertEqual(payload.action, "timeout")
        self.assertEqual(payload.client_request_id, "system-timeout:question-1")

    async def test_due_question_for_a_terminal_run_is_cancelled_without_retrying(self) -> None:
        question = SimpleNamespace(
            id="question-orphaned",
            run_id="run-terminal",
            document_id=3,
            session_id=2,
            user_id=7,
            status=ChatUserQuestionStatus.WAITING,
            timeout_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            last_activity_at=None,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=2),
            answer_json="{}",
            answered_at=None,
        )
        run = SimpleNamespace(status=AgentRunStatus.FAILED)

        class FakeQuery:
            def filter(self, *_args):
                return self

            def populate_existing(self):
                return self

            def with_for_update(self):
                return self

            def one_or_none(self):
                return question

        class FakeSession:
            def rollback(self):
                pass

            committed = False

            def query(self, _model):
                return FakeQuery()

            def get(self, model, _identifier):
                return run if model is AgentRun else None

            def commit(self) -> None:
                self.committed = True

            def close(self) -> None:
                pass

        session = FakeSession()
        resume = AsyncMock()
        with (
            patch.object(chat_module, "SessionLocal", return_value=session),
            patch.object(chat_module, "answer_chat_user_question", resume),
        ):
            completed = await chat_module._auto_answer_timed_out_user_question(question.id)

        self.assertTrue(completed)
        self.assertTrue(session.committed)
        self.assertEqual(question.status, ChatUserQuestionStatus.CANCELLED)
        self.assertIn("run_not_waiting_for_input", question.answer_json)
        resume.assert_not_awaited()

    async def test_startup_restoration_cancels_orphaned_questions_and_schedules_valid_ones(self) -> None:
        orphaned = SimpleNamespace(
            id="question-orphaned",
            run_id="run-failed",
            status=ChatUserQuestionStatus.WAITING,
            answer_json="{}",
            answered_at=None,
        )
        valid = SimpleNamespace(
            id="question-valid",
            run_id="run-waiting",
            status=ChatUserQuestionStatus.WAITING,
        )
        failed_run = SimpleNamespace(status=AgentRunStatus.FAILED)
        waiting_run = SimpleNamespace(status=AgentRunStatus.WAITING_FOR_INPUT)

        class FakeQuery:
            calls = 0

            def outerjoin(self, *_args):
                return self

            def filter(self, *_args):
                return self

            def options(self, *_args):
                return self

            def order_by(self, *_args):
                return self

            def limit(self, *_args):
                return self

            def all(self):
                FakeQuery.calls += 1
                return [(orphaned, failed_run), (valid, waiting_run)] if FakeQuery.calls == 1 else []

        class FakeSession:
            def rollback(self):
                pass

            committed = False

            def query(self, *_models):
                return FakeQuery()

            def commit(self) -> None:
                self.committed = True

            def close(self) -> None:
                pass

        session = FakeSession()
        schedule = Mock()
        with (
            patch.object(chat_module, "SessionLocal", return_value=session),
            patch.object(chat_module, "schedule_user_question_timeout", schedule),
        ):
            await chat_module.restore_waiting_user_question_timeouts()

        self.assertTrue(session.committed)
        self.assertEqual(orphaned.status, ChatUserQuestionStatus.CANCELLED)
        schedule.assert_called_once_with(valid.id)

    def test_user_question_activity_refreshes_the_durable_deadline(self) -> None:
        run = SimpleNamespace(
            id="run-1",
            document_id=3,
            user_id=7,
            status=AgentRunStatus.WAITING_FOR_INPUT,
        )
        question = SimpleNamespace(
            id="question-1",
            run_id="run-1",
            user_id=7,
            status=ChatUserQuestionStatus.WAITING,
            last_activity_at=None,
            timeout_at=None,
        )

        class FakeQuery:
            def __init__(self, value):
                self.value = value

            def filter(self, *_args):
                return self

            def populate_existing(self):
                return self

            def with_for_update(self):
                return self

            def one_or_none(self):
                return self.value

        class FakeSession:
            def rollback(self):
                pass

            committed = False

            def query(self, model):
                return FakeQuery(run if model is AgentRun else question)

            def commit(self) -> None:
                self.committed = True

        session = FakeSession()
        with patch.object(chat_module, "_get_accessible_document"):
            result = chat_module.record_chat_user_question_activity(3, "run-1", "question-1", SimpleNamespace(id=7), session)

        self.assertTrue(session.committed)
        self.assertIsNotNone(question.last_activity_at)
        self.assertEqual(result.timeout_at, question.timeout_at)
        self.assertGreater((question.timeout_at - question.last_activity_at).total_seconds(), 119)

    def test_agent_execution_error_prefix_is_not_duplicated(self) -> None:
        self.assertEqual(
            _agent_execution_error_message("Agent 执行失败: 上游错误"),
            "Agent 执行失败: 上游错误",
        )
        self.assertEqual(
            _agent_execution_error_message("上游错误"),
            "Agent 执行失败: 上游错误",
        )
        self.assertEqual(
            _agent_execution_error_message("Concurrency limit exceeded for account, please retry later"),
            "当前模型服务繁忙或并发已满。请稍后重试，或更换其他可用模型后重新发送本轮请求。",
        )
        self.assertEqual(
            _agent_execution_error_message("Error code: 503 - Service is too busy"),
            "当前模型服务繁忙或并发已满。请稍后重试，或更换其他可用模型后重新发送本轮请求。",
        )

    def test_recognises_provider_context_limit_errors_for_safe_retry(self) -> None:
        self.assertTrue(_is_context_limit_error("maximum context length exceeded"))
        self.assertTrue(_is_context_limit_error("input is too large for this model"))
        self.assertFalse(_is_context_limit_error("provider connection timed out"))

    def test_interrupted_tool_parameter_generation_is_not_reported_as_execution_failure(self) -> None:
        tools = [{"id": "tool-1", "name": "replace_full_html", "status": "running", "preparing": True}]
        blocks = [{"type": "tool", "state": "done", "tool": tools[0]}]

        self.assertTrue(_settle_terminal_timeline(tools, blocks))
        self.assertEqual(tools[0]["status"], "error")
        self.assertFalse(tools[0]["preparing"])
        self.assertEqual(tools[0]["result"], "模型未完成工具参数生成，工具尚未执行。")

    def test_unresolved_edit_failure_overrides_a_success_claim(self) -> None:
        failed_tools = [{"name": "apply_html_patch", "status": "error"}]
        recovered_tools = [
            {"name": "apply_html_patch", "status": "error"},
            {"name": "apply_html_patch", "status": "success"},
        ]

        outcome = _unresolved_edit_failure(failed_tools)

        self.assertIsNotNone(outcome)
        self.assertIn("未完成", outcome[0])
        self.assertIsNone(_unresolved_edit_failure(recovered_tools))

    def test_direct_image_checkpoint_is_not_an_external_document_conflict(self) -> None:
        source = "<p>原稿</p>"
        own_image_replacement = '<p><img src="/api/documents/local-images/edited.png" /></p>'

        self.assertFalse(
            _has_external_document_conflict(
                source,
                own_image_replacement,
                own_image_replacement,
                set(),
            )
        )
        self.assertTrue(
            _has_external_document_conflict(
                source,
                own_image_replacement,
                "<p>其他人修改</p>",
                {own_image_replacement},
            )
        )

    def test_restart_failure_events_are_plain_payloads(self) -> None:
        events = _restart_failure_events("服务已重启", "<p>保留稿</p>")

        self.assertEqual([event["event"] for event in events], ["error", "final"])
        final = json.loads(events[1]["data"])
        self.assertEqual(final["content"], "服务已重启")
        self.assertEqual(final["html"], "<p>保留稿</p>")
        self.assertEqual(final["run_status"], "failed")
        self.assertEqual(final["partial_save_state"], "none")
        self.assertIsNone(final["compliance"])

    def test_restart_failure_event_marks_a_preserved_candidate_as_changed(self) -> None:
        events = _restart_failure_events("服务已重启", "<p>保留稿</p>", "preserved")

        final = json.loads(events[1]["data"])
        self.assertTrue(final["html_changed"])
        self.assertEqual(final["partial_save_state"], "preserved")

    def test_mysql_disconnect_is_retryable_for_terminal_persistence(self) -> None:
        exc = DBAPIError.instance(
            "SELECT 1",
            {},
            RuntimeError("Lost connection to MySQL server during query"),
            Exception,
            connection_invalidated=True,
        )

        self.assertTrue(_is_retryable_db_disconnect(exc))
        self.assertFalse(_is_retryable_db_disconnect(ValueError("invalid terminal data")))

    async def test_heartbeat_events_keep_a_long_tool_argument_stream_alive(self) -> None:
        async def events():
            for _ in range(4):
                await asyncio.sleep(0.01)
                yield {"event": "heartbeat", "data": {"detail": "模型正在生成工具参数"}}

        with (
            patch("app.api.routes.chat.AGENT_EVENT_IDLE_TIMEOUT_SECONDS", 0.1),
            patch("app.api.routes.chat.AGENT_MAX_RUNTIME_SECONDS", 1.0),
        ):
            received = [event async for event in _iterate_agent_events_with_timeout(events())]

        self.assertEqual(len(received), 4)
        self.assertTrue(all(event["event"] == "heartbeat" for event in received))

    async def test_preparing_tool_call_uses_the_tool_argument_idle_limit(self) -> None:
        async def events():
            yield {"event": "tool_call", "data": {"id": "tool-1", "preparing": True}}
            await asyncio.sleep(0.02)
            yield {"event": "tool_result", "data": {"id": "tool-1"}}

        with (
            patch("app.api.routes.chat.AGENT_EVENT_IDLE_TIMEOUT_SECONDS", 0.01),
            patch("app.api.routes.chat.AGENT_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS", 0.05),
            patch("app.api.routes.chat.AGENT_MAX_RUNTIME_SECONDS", 1.0),
        ):
            received = [event async for event in _iterate_agent_events_with_timeout(events())]

        self.assertEqual([event["event"] for event in received], ["tool_call", "tool_result"])

    async def test_preparing_tool_call_timeout_has_a_tool_argument_reason(self) -> None:
        async def events():
            yield {"event": "tool_call", "data": {"id": "tool-1", "preparing": True}}
            await asyncio.sleep(1)

        with (
            patch("app.api.routes.chat.AGENT_EVENT_IDLE_TIMEOUT_SECONDS", 1.0),
            patch("app.api.routes.chat.AGENT_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS", 0.01),
            patch("app.api.routes.chat.AGENT_MAX_RUNTIME_SECONDS", 1.0),
        ):
            with self.assertRaisesRegex(RuntimeError, "工具参数"):
                async for _ in _iterate_agent_events_with_timeout(events()):
                    pass

    async def test_total_runtime_limit_stops_an_endless_heartbeat_stream(self) -> None:
        async def events():
            while True:
                await asyncio.sleep(0.005)
                yield {"event": "heartbeat", "data": {}}

        with (
            patch("app.api.routes.chat.AGENT_EVENT_IDLE_TIMEOUT_SECONDS", 0.1),
            patch("app.api.routes.chat.AGENT_MAX_RUNTIME_SECONDS", 0.08),
        ):
            with self.assertRaisesRegex(RuntimeError, "总时限"):
                async for _ in _iterate_agent_events_with_timeout(events()):
                    pass

    async def test_model_turn_finalization_has_a_shorter_idle_timeout(self) -> None:
        async def events():
            yield {
                "event": "heartbeat",
                "data": {"phase": "model_turn_finalizing", "detail": "正在整理本轮模型响应"},
            }
            await asyncio.sleep(1)

        with (
            patch("app.api.routes.chat.AGENT_EVENT_IDLE_TIMEOUT_SECONDS", 1.0),
            patch("app.api.routes.chat.AGENT_TURN_FINALIZATION_TIMEOUT_SECONDS", 0.01),
            patch("app.api.routes.chat.AGENT_MAX_RUNTIME_SECONDS", 2.0),
        ):
            with self.assertRaisesRegex(RuntimeError, "本轮响应整理"):
                async for _ in _iterate_agent_events_with_timeout(events()):
                    pass

    async def test_context_stats_after_finalizing_does_not_relax_the_short_timeout(self) -> None:
        async def events():
            yield {
                "event": "heartbeat",
                "data": {"phase": "model_turn_finalizing", "detail": "正在整理本轮模型响应"},
            }
            yield {"event": "context_stats", "data": {"state": "measured", "used_tokens": 1}}
            await asyncio.sleep(1)

        with (
            patch("app.api.routes.chat.AGENT_EVENT_IDLE_TIMEOUT_SECONDS", 1.0),
            patch("app.api.routes.chat.AGENT_TURN_FINALIZATION_TIMEOUT_SECONDS", 0.01),
            patch("app.api.routes.chat.AGENT_MAX_RUNTIME_SECONDS", 2.0),
        ):
            with self.assertRaisesRegex(RuntimeError, "本轮响应整理"):
                async for _ in _iterate_agent_events_with_timeout(events()):
                    pass

    async def test_stalled_tool_argument_stream_fails_without_waiting_for_agent_idle_timeout(self) -> None:
        async def stream():
            yield SimpleNamespace(tool_call_chunks=[{"index": 0, "name": "inspect_history_images"}])
            await asyncio.sleep(1)

        with patch("app.services.chat_agent.MODEL_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(RuntimeError, "工具参数") as raised:
                async for _ in _iterate_model_stream_with_idle_limits(stream()):
                    pass
        self.assertEqual(raised.exception.phase, "tool_argument_idle")

    async def test_repeated_tool_control_chunks_do_not_keep_the_run_alive(self) -> None:
        async def stream():
            while True:
                yield SimpleNamespace(tool_call_chunks=[{"index": 0, "name": "replace_document", "args": ""}])
                await asyncio.sleep(0.002)

        with (
            patch("app.services.chat_agent.MODEL_FIRST_PROGRESS_TIMEOUT_SECONDS", 0.02),
            patch("app.services.chat_agent.MODEL_STREAM_IDLE_TIMEOUT_SECONDS", 0.02),
            patch("app.services.chat_agent.MODEL_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS", 0.02),
        ):
            with self.assertRaises(ModelStreamTimeoutError) as raised:
                async for _ in _iterate_model_stream_with_idle_limits(stream()):
                    pass
        self.assertEqual(raised.exception.phase, "tool_argument_idle")

    async def test_continuous_tool_argument_output_is_not_limited_by_total_duration(self) -> None:
        async def stream():
            for index in range(12):
                yield SimpleNamespace(tool_call_chunks=[{"index": 0, "name": "replace_document", "args": str(index)}])
                await asyncio.sleep(0.02)

        with patch("app.services.chat_agent.MODEL_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS", 0.05):
            received = [chunk async for chunk in _iterate_model_stream_with_idle_limits(stream())]

        self.assertEqual(len(received), 12)

    async def test_stalled_model_stream_fails_before_the_long_agent_timeout(self) -> None:
        async def stream():
            await asyncio.sleep(1)
            yield SimpleNamespace(tool_call_chunks=[])

        with (
            patch("app.services.chat_agent.MODEL_FIRST_PROGRESS_TIMEOUT_SECONDS", 0.01),
            patch("app.services.chat_agent.MODEL_STREAM_IDLE_TIMEOUT_SECONDS", 0.01),
        ):
            with self.assertRaises(ModelStreamTimeoutError) as raised:
                async for _ in _iterate_model_stream_with_idle_limits(stream()):
                    pass
        self.assertEqual(raised.exception.phase, "first_progress")

    async def test_empty_provider_chunks_do_not_keep_thinking_alive(self) -> None:
        async def stream():
            while True:
                yield AIMessageChunk(content="")
                await asyncio.sleep(0.002)

        with (
            patch("app.services.chat_agent.MODEL_FIRST_PROGRESS_TIMEOUT_SECONDS", 0.02),
            patch("app.services.chat_agent.MODEL_STREAM_IDLE_TIMEOUT_SECONDS", 0.02),
        ):
            with self.assertRaises(ModelStreamTimeoutError) as raised:
                async for _ in _iterate_model_stream_with_idle_limits(stream()):
                    pass
        self.assertEqual(raised.exception.phase, "first_progress")

    async def test_non_cooperative_stream_closure_is_a_terminal_cleanup_failure(self) -> None:
        release = asyncio.Event()
        closed = asyncio.Event()
        reading = False
        close_count = 0

        class StubbornStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                nonlocal reading
                reading = True
                try:
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        await release.wait()
                    raise StopAsyncIteration
                finally:
                    reading = False

            async def aclose(self):
                nonlocal close_count
                close_count += 1
                if reading:
                    raise RuntimeError("aclose(): asynchronous generator is already running")
                closed.set()

        try:
            with (
                patch("app.services.chat_agent.MODEL_FIRST_PROGRESS_TIMEOUT_SECONDS", 0.01),
                patch("app.services.chat_agent.MODEL_STREAM_CLEANUP_GRACE_SECONDS", 0.01),
            ):
                with self.assertRaises(ModelStreamCleanupError):
                    async for _ in _iterate_model_stream_with_idle_limits(StubbornStream()):
                        pass
                self.assertEqual(close_count, 0)
        finally:
            release.set()
            await asyncio.wait_for(closed.wait(), timeout=1)
        self.assertEqual(close_count, 1)

    async def test_cancelled_model_stream_stops_pending_read_before_closing(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        stopped = asyncio.Event()

        async def stream():
            try:
                started.set()
                await release.wait()
                yield AIMessageChunk(content="late output")
            finally:
                stopped.set()

        async def consume():
            async for _ in _iterate_model_stream_with_idle_limits(stream()):
                pass

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            with patch("app.services.chat_agent.logger.warning") as warning:
                task.cancel("user stopped the run")
                with self.assertRaises(asyncio.CancelledError) as raised:
                    await asyncio.wait_for(task, timeout=1)
                self.assertEqual(raised.exception.args, ("user stopped the run",))
                self.assertTrue(stopped.is_set())
                warning.assert_not_called()
        finally:
            release.set()
            await asyncio.wait_for(stopped.wait(), timeout=1)

    async def test_stubborn_model_read_defers_close_and_preserves_cancellation(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        closed = asyncio.Event()
        reading = False
        close_count = 0

        class StubbornStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                nonlocal reading
                reading = True
                started.set()
                try:
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        await release.wait()
                    raise StopAsyncIteration
                finally:
                    reading = False

            async def aclose(self):
                nonlocal close_count
                close_count += 1
                if reading:
                    raise RuntimeError("aclose(): asynchronous generator is already running")
                closed.set()

        async def consume():
            async for _ in _iterate_model_stream_with_idle_limits(StubbornStream()):
                pass

        with patch("app.services.chat_agent.MODEL_STREAM_CLEANUP_GRACE_SECONDS", 0.01):
            task = asyncio.create_task(consume())
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=1)
                self.assertEqual(close_count, 0)
            finally:
                release.set()
                await asyncio.wait_for(closed.wait(), timeout=1)
            self.assertEqual(close_count, 1)

    async def test_repeated_cancellation_does_not_interrupt_model_stream_cleanup(self) -> None:
        started = asyncio.Event()
        stopping = asyncio.Event()
        release = asyncio.Event()
        closed = asyncio.Event()

        class Stream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopping.set()
                    await release.wait()

            async def aclose(self):
                closed.set()

        async def consume():
            async for _ in _iterate_model_stream_with_idle_limits(Stream()):
                pass

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel("first cancellation")
            await asyncio.wait_for(stopping.wait(), timeout=1)
            task.cancel("second cancellation")
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
            self.assertFalse(closed.is_set())
        finally:
            release.set()
            await asyncio.wait_for(closed.wait(), timeout=1)

    async def test_anyio_scope_cancellation_still_cleans_up_model_stream(self) -> None:
        started = asyncio.Event()
        stopped = asyncio.Event()
        scopes = []

        async def stream():
            try:
                started.set()
                await asyncio.Event().wait()
                yield AIMessageChunk(content="late output")
            finally:
                stopped.set()

        async def consume():
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                async for _ in _iterate_model_stream_with_idle_limits(stream()):
                    pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=1)
        with patch("app.services.chat_agent.logger.warning") as warning:
            scopes[0].cancel()
            await asyncio.wait_for(task, timeout=1)
            await asyncio.wait_for(stopped.wait(), timeout=1)
            warning.assert_not_called()

    async def test_force_stuck_cancellation_persists_terminal_result(self) -> None:
        run = SimpleNamespace(
            id="stuck-run",
            session_id=3,
            user_message_id=0,
            status=AgentRunStatus.CANCELLING,
            assistant_message_id=None,
            error_message="",
            finished_at=None,
        )
        document = SimpleNamespace(id=7, current_html="<p>draft</p>")

        class FakeSession:
            def rollback(self):
                pass

            def __init__(self) -> None:
                self.message = None
                self.committed = False
                self.closed = False

            def get(self, model, _identifier):
                if model is AgentRun:
                    return run
                if model is Document:
                    return document
                return None

            def query(self, _model):
                if _model is ChatUserQuestion:
                    return SimpleNamespace(filter=lambda *_args: SimpleNamespace(
                        order_by=lambda *_args: SimpleNamespace(first=lambda: None)))
                result = run if _model is AgentRun else document
                return SimpleNamespace(
                    filter=lambda *_args: SimpleNamespace(
                        with_for_update=lambda: SimpleNamespace(first=lambda: result),
                        order_by=lambda *_args: SimpleNamespace(all=lambda: [])
                    )
                )

            def add(self, message) -> None:
                if isinstance(message, ChatMessage):
                    self.message = message

            def flush(self) -> None:
                self.message.id = 11

            def commit(self) -> None:
                self.committed = True

            def close(self) -> None:
                self.closed = True

        session = FakeSession()
        manager = AgentRunManager()
        manager.create(run.id).status = AgentRunStatus.CANCELLING.value

        async def mark_terminal(run_id: str, status: str) -> None:
            manager.get(run_id).status = status

        with (
            patch.object(chat_module, "CANCEL_GRACE_SECONDS", 0),
            patch.object(chat_module, "SessionLocal", return_value=session),
            patch.object(chat_module, "agent_run_manager", manager),
            patch("app.services.wechat_compliance.get_official_compliance_engine", side_effect=AssertionError("Unexpected automatic check")),
            patch.object(manager, "publish"),
            patch.object(manager, "mark_terminal", side_effect=mark_terminal),
        ):
            await _force_stuck_cancellation(run.id, document.id)

        self.assertTrue(session.committed)
        self.assertTrue(session.closed)
        self.assertEqual(run.status, AgentRunStatus.CANCELLED)
        self.assertEqual(run.assistant_message_id, 11)
        self.assertEqual(run.owner_id, "")
        self.assertIsNone(run.lease_expires_at)
        self.assertEqual(manager.get(run.id).status, AgentRunStatus.CANCELLED.value)

    async def test_force_stuck_cancellation_preserves_checkpoint_when_document_is_unchanged(self) -> None:
        source_html = "<p>source</p>"
        checkpoint_html = "<p>completed patch</p>"
        run = SimpleNamespace(
            id="checkpoint-run",
            session_id=3,
            user_id=1,
            user_message_id=12,
            checkpoint_html=checkpoint_html,
            status=AgentRunStatus.CANCELLING,
            assistant_message_id=None,
            error_message="",
            finished_at=None,
        )
        document = SimpleNamespace(id=7, current_html=source_html, group=None)
        request_message = SimpleNamespace(html_before=source_html)

        class FakeSession:
            def rollback(self):
                pass

            def __init__(self) -> None:
                self.message = None

            def get(self, model, _identifier):
                if model is AgentRun:
                    return run
                if model is ChatMessage:
                    return request_message
                return None

            def query(self, _model):
                if _model is ChatUserQuestion:
                    return SimpleNamespace(filter=lambda *_args: SimpleNamespace(
                        order_by=lambda *_args: SimpleNamespace(first=lambda: None)))
                result = run if _model is AgentRun else document
                return SimpleNamespace(
                    filter=lambda *_args: SimpleNamespace(
                        with_for_update=lambda: SimpleNamespace(first=lambda: result),
                        order_by=lambda *_args: SimpleNamespace(all=lambda: [])
                    )
                )

            def add(self, message) -> None:
                if isinstance(message, ChatMessage):
                    self.message = message

            def flush(self) -> None:
                self.message.id = 11

            def commit(self) -> None:
                pass

            def close(self) -> None:
                pass

        session = FakeSession()
        manager = AgentRunManager()
        manager.create(run.id).status = AgentRunStatus.CANCELLING.value

        async def mark_terminal(run_id: str, status: str) -> None:
            manager.get(run_id).status = status

        with (
            patch.object(chat_module, "CANCEL_GRACE_SECONDS", 0),
            patch.object(chat_module, "SessionLocal", return_value=session),
            patch.object(chat_module, "agent_run_manager", manager),
            patch("app.services.wechat_compliance.get_official_compliance_engine", side_effect=AssertionError("Unexpected automatic check")),
            patch("app.services.agent_checkpoints.touch_document"),
            patch("app.services.agent_checkpoints.create_document_version"),
            patch.object(manager, "publish"),
            patch.object(manager, "mark_terminal", side_effect=mark_terminal),
        ):
            await _force_stuck_cancellation(run.id, document.id)

        self.assertEqual(document.current_html, checkpoint_html)
        self.assertEqual(session.message.html_after, checkpoint_html)
        self.assertIn("已保留", run.error_message)

    async def test_force_stuck_cancellation_never_overwrites_external_document_change(self) -> None:
        source_html = "<p>source</p>"
        external_html = "<p>external edit</p>"
        checkpoint_html = "<p>completed patch</p>"
        run = SimpleNamespace(
            id="checkpoint-conflict-run",
            session_id=3,
            user_id=1,
            user_message_id=12,
            checkpoint_html=checkpoint_html,
            status=AgentRunStatus.CANCELLING,
            assistant_message_id=None,
            error_message="",
            finished_at=None,
        )
        document = SimpleNamespace(id=7, current_html=external_html, group=None)
        request_message = SimpleNamespace(html_before=source_html)

        class FakeSession:
            def rollback(self):
                pass

            def __init__(self) -> None:
                self.message = None

            def get(self, model, _identifier):
                if model is AgentRun:
                    return run
                if model is ChatMessage:
                    return request_message
                return None

            def query(self, _model):
                if _model is ChatUserQuestion:
                    return SimpleNamespace(filter=lambda *_args: SimpleNamespace(
                        order_by=lambda *_args: SimpleNamespace(first=lambda: None)))
                result = run if _model is AgentRun else document
                return SimpleNamespace(
                    filter=lambda *_args: SimpleNamespace(
                        with_for_update=lambda: SimpleNamespace(first=lambda: result),
                        order_by=lambda *_args: SimpleNamespace(all=lambda: [])
                    )
                )

            def add(self, message) -> None:
                if isinstance(message, ChatMessage):
                    self.message = message

            def flush(self) -> None:
                self.message.id = 11

            def commit(self) -> None:
                pass

            def close(self) -> None:
                pass

        session = FakeSession()
        manager = AgentRunManager()
        manager.create(run.id).status = AgentRunStatus.CANCELLING.value

        async def mark_terminal(run_id: str, status: str) -> None:
            manager.get(run_id).status = status

        with (
            patch.object(chat_module, "CANCEL_GRACE_SECONDS", 0),
            patch.object(chat_module, "SessionLocal", return_value=session),
            patch.object(chat_module, "agent_run_manager", manager),
            patch("app.services.wechat_compliance.get_official_compliance_engine", side_effect=AssertionError("Unexpected automatic check")),
            patch("app.services.agent_checkpoints.create_document_version") as create_version,
            patch.object(manager, "publish"),
            patch.object(manager, "mark_terminal", side_effect=mark_terminal),
        ):
            await _force_stuck_cancellation(run.id, document.id)

        self.assertEqual(document.current_html, external_html)
        self.assertIsNone(session.message.html_after)
        self.assertEqual(run.checkpoint_html, checkpoint_html)
        self.assertIn("未自动覆盖", run.error_message)
        create_version.assert_not_called()

    def test_startup_recovery_preserves_checkpointed_edit(self) -> None:
        source_html = "<p>source</p>"
        checkpoint_html = "<p>completed patch</p>"
        run = SimpleNamespace(
            id="restart-run",
            document_id=7,
            session_id=3,
            user_id=1,
            user_message_id=12,
            checkpoint_html=checkpoint_html,
            status=AgentRunStatus.RUNNING,
            assistant_message_id=None,
            error_message="",
            finished_at=None,
            created_at=0,
        )
        document = SimpleNamespace(id=7, current_html=source_html, group=None)
        request_message = SimpleNamespace(html_before=source_html)

        class FakeQuery:
            def __init__(self, rows):
                self.rows = rows

            def filter(self, *_args):
                return self

            def order_by(self, *_args):
                return self

            def limit(self, *_args):
                return self

            def scalar(self):
                return getattr(self.rows[0], "sequence", None) if self.rows else None

            def populate_existing(self):
                return self

            def with_for_update(self):
                return self

            def all(self):
                return self.rows

            def first(self):
                return self.rows[0] if self.rows else None

        class FakeSession:
            def rollback(self):
                pass

            def __init__(self) -> None:
                self.message = None
                self.events = []
                self.committed = False

            def query(self, model):
                return FakeQuery([run] if model is AgentRun else [document] if model is Document else [])

            def get(self, model, _identifier):
                return request_message if model is ChatMessage else None

            def add(self, message) -> None:
                if isinstance(message, ChatMessage):
                    self.message = message
                else:
                    self.events.append(message)

            def flush(self) -> None:
                self.message.id = 11

            def commit(self) -> None:
                self.committed = True

        session = FakeSession()
        with (
            patch("app.services.agent_checkpoints.touch_document"),
            patch("app.services.agent_checkpoints.create_document_version"),
            patch("app.services.wechat_compliance.get_official_compliance_engine", side_effect=AssertionError("Unexpected automatic check")),
        ):
            recovered = bootstrap_module.recover_interrupted_agent_runs(session)

        self.assertEqual(recovered, 1)
        self.assertTrue(session.committed)
        self.assertEqual(document.current_html, checkpoint_html)
        self.assertEqual(run.status, AgentRunStatus.FAILED)
        self.assertEqual(session.message.html_before, source_html)
        self.assertEqual(session.message.html_after, checkpoint_html)
        terminal_events = [event for event in session.events if getattr(event, "event", "") == "final"]
        self.assertEqual(len(terminal_events), 1)
        self.assertIn("已保留", run.error_message)


if __name__ == "__main__":
    unittest.main()
