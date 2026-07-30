import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all metadata dependencies
import app.services.agent_run_manager as manager_module
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.services.agent_run_manager import AgentRunManager


class AgentRunManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def _persist_run(
        self,
        manager: AgentRunManager,
        run_id: str,
        status: AgentRunStatus = AgentRunStatus.RUNNING,
    ) -> None:
        with self.Session() as db:
            db.add(
                AgentRun(
                    id=run_id,
                    document_id=1,
                    session_id=1,
                    user_id=1,
                    user_message_id=1,
                    client_request_id=f"request-{run_id}",
                    status=status,
                    owner_id=manager.worker_id,
                )
            )
            db.commit()

    async def test_replays_published_event(self) -> None:
        writer = AgentRunManager()
        writer.create("run-1")
        self._persist_run(writer, "run-1")

        with patch.object(manager_module, "SessionLocal", self.Session):
            await writer.publish("run-1", "text_delta", {"text": "hello"})
            # A different worker has no local event cache but replays the
            # durable event from the shared database.
            reader = AgentRunManager()
            events = reader.events_after("run-1", 0)
            event = await anext(events)
            await events.aclose()

        self.assertEqual(event.sequence, 1)
        self.assertEqual(event.event, "text_delta")
        self.assertEqual(event.data, {"text": "hello"})

    async def test_emits_heartbeat_while_waiting_for_agent_output(self) -> None:
        manager = AgentRunManager()
        manager.create("run-2")
        self._persist_run(manager, "run-2")
        previous_interval = manager_module.HEARTBEAT_INTERVAL_SECONDS
        previous_poll_interval = manager_module.EVENT_POLL_INTERVAL_SECONDS
        manager_module.HEARTBEAT_INTERVAL_SECONDS = 0.01
        manager_module.EVENT_POLL_INTERVAL_SECONDS = 0.01
        try:
            with patch.object(manager_module, "SessionLocal", self.Session):
                events = manager.events_after("run-2", 0)
                event = await anext(events)
                await events.aclose()
        finally:
            manager_module.HEARTBEAT_INTERVAL_SECONDS = previous_interval
            manager_module.EVENT_POLL_INTERVAL_SECONDS = previous_poll_interval

        self.assertEqual(event.sequence, 0)
        self.assertEqual(event.event, "heartbeat")
        self.assertEqual(event.data["status"], "running")

    async def test_waiting_for_user_input_closes_the_event_stream_without_a_failure(self) -> None:
        manager = AgentRunManager()
        manager.create("run-waiting")
        self._persist_run(manager, "run-waiting", AgentRunStatus.WAITING_FOR_INPUT)

        with patch.object(manager_module, "SessionLocal", self.Session):
            events = manager.events_after("run-waiting", 0)
            with self.assertRaises(StopAsyncIteration):
                await anext(events)
            await events.aclose()
