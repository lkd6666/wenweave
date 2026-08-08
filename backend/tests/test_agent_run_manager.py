import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all metadata dependencies
import app.services.agent_run_manager as manager_module
from app.db.base import Base
from app.bootstrap import recover_expired_agent_runs
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_run_event import AgentRunEvent
from app.models.model_call_record import ModelCallRecord, ModelCallSource, ModelCallStatus
from app.services.agent_run_manager import AgentRunEventBacklogError, AgentRunManager, PendingRunEvent


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

    def test_worker_identity_is_unique_when_instance_label_is_shared(self) -> None:
        first = manager_module._build_worker_id("baota-production")
        second = manager_module._build_worker_id("baota-production")

        self.assertTrue(first.startswith("baota-production:"))
        self.assertTrue(second.startswith("baota-production:"))
        self.assertNotEqual(first, second)

    async def test_live_foreign_worker_cannot_claim_same_run(self) -> None:
        owner = AgentRunManager()
        owner.worker_id = "baota:111:owner"
        contender = AgentRunManager()
        contender.worker_id = "baota:222:contender"
        run_id = "run-foreign-owner"
        self._persist_run(owner, run_id)
        with self.Session() as db:
            run = db.get(AgentRun, run_id)
            assert run is not None
            run.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
            db.commit()

        with patch.object(manager_module, "SessionLocal", self.Session):
            claimed = await contender.mark_started(run_id)
            with self.Session() as db:
                run = db.get(AgentRun, run_id)

        assert run is not None
        self.assertIsNone(claimed)
        self.assertEqual(run.owner_id, owner.worker_id)

    def test_retries_only_event_sequence_unique_collision(self) -> None:
        manager = AgentRunManager()
        collision = IntegrityError(
            "INSERT INTO agent_run_events",
            {},
            Exception("(1062, Duplicate entry for key 'uq_agent_run_events_run_sequence')"),
        )
        persisted = []
        with patch.object(manager, "_persist_events_once", side_effect=[collision, persisted]) as write_once:
            result = manager._persist_events(
                "run-collision-retry",
                [PendingRunEvent(event="heartbeat", data={}, payload_bytes=2)],
                force=False,
            )

        self.assertEqual(result, persisted)
        self.assertEqual(write_once.call_count, 2)

    async def test_replays_published_event(self) -> None:
        writer = AgentRunManager()
        writer.create("run-1")
        self._persist_run(writer, "run-1")

        with patch.object(manager_module, "SessionLocal", self.Session):
            await writer.publish("run-1", "text_delta", {"text": "hello"})
            await writer.flush("run-1")
            # A different worker has no local event cache but replays the
            # durable event from the shared database.
            reader = AgentRunManager()
            events = reader.events_after("run-1", 0)
            event = await anext(events)
            await events.aclose()

        self.assertEqual(event.sequence, 1)
        self.assertEqual(event.event, "text_delta")
        self.assertEqual(event.data, {"text": "hello"})

    async def test_forwards_token_to_local_stream_before_batch_flush(self) -> None:
        manager = AgentRunManager()
        run_id = "run-realtime"
        manager.create(run_id)
        self._persist_run(manager, run_id)

        with patch.object(manager_module, "SessionLocal", self.Session):
            events = manager.events_after(run_id, 0)
            next_event = asyncio.create_task(anext(events))
            await asyncio.sleep(0)
            await manager.publish(run_id, "text_delta", {"text": "live token"})
            event = await asyncio.wait_for(next_event, timeout=0.2)
            await events.aclose()
            await manager.flush(run_id)

        self.assertEqual(event.sequence, 0)
        self.assertEqual(event.event, "text_delta")
        self.assertTrue(event.data["_transient"])
        self.assertEqual(event.data["text"], "live token")

    async def test_coalesces_thousands_of_token_deltas_and_reconstructs_text(self) -> None:
        manager = AgentRunManager()
        run_id = "run-burst"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        source = "x" * 7_415

        with patch.object(manager_module, "SessionLocal", self.Session):
            for character in source:
                await manager.publish(run_id, "reasoning_delta", {"text": character})
            await manager.flush(run_id)
            with self.Session() as db:
                rows = (
                    db.query(AgentRunEvent)
                    .filter(AgentRunEvent.run_id == run_id, AgentRunEvent.event == "reasoning_delta")
                    .order_by(AgentRunEvent.sequence)
                    .all()
                )

        self.assertLess(len(rows), 8)
        self.assertEqual("".join(json.loads(row.payload_json)["text"] for row in rows), source)

    async def test_context_stats_keeps_only_latest_pending_snapshot(self) -> None:
        manager = AgentRunManager()
        run_id = "run-context-stats"
        manager.create(run_id)
        self._persist_run(manager, run_id)

        with patch.object(manager_module, "SessionLocal", self.Session):
            for index in range(10):
                await manager.publish(run_id, "context_stats", {"state": "running", "count": index})
            await manager.flush(run_id)
            with self.Session() as db:
                rows = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run_id).all()

        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0].payload_json)["count"], 9)

    async def test_repairs_stale_sequence_cursor_before_appending(self) -> None:
        manager = AgentRunManager()
        run_id = "run-stale-event-sequence"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        with self.Session() as db:
            run = db.get(AgentRun, run_id)
            assert run is not None
            run.event_sequence = 3
            db.add(
                AgentRunEvent(
                    run_id=run_id,
                    sequence=8,
                    event="heartbeat",
                    payload_json='{"phase":"before-deployment"}',
                )
            )
            db.commit()

        with patch.object(manager_module, "SessionLocal", self.Session):
            await manager.publish(run_id, "heartbeat", {"phase": "model_turn_started"})
            with self.Session() as db:
                run = db.get(AgentRun, run_id)
                rows = (
                    db.query(AgentRunEvent)
                    .filter(AgentRunEvent.run_id == run_id)
                    .order_by(AgentRunEvent.sequence)
                    .all()
                )

        assert run is not None
        self.assertEqual([row.sequence for row in rows], [8, 9])
        self.assertEqual(run.event_sequence, 9)

    async def test_critical_event_flushes_prior_deltas_in_order(self) -> None:
        manager = AgentRunManager()
        run_id = "run-boundary"
        manager.create(run_id)
        self._persist_run(manager, run_id)

        with patch.object(manager_module, "SessionLocal", self.Session):
            await manager.publish(run_id, "text_delta", {"text": "before tool"})
            await manager.publish(run_id, "tool_call", {"id": "tool-1", "name": "read_blocks"})
            with self.Session() as db:
                rows = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run_id).order_by(AgentRunEvent.sequence).all()

        self.assertEqual([row.event for row in rows], ["text_delta", "tool_call"])
        self.assertEqual(json.loads(rows[0].payload_json)["text"], "before tool")

    async def test_pending_buffer_limit_fails_before_memory_grows_without_bound(self) -> None:
        manager = AgentRunManager()
        run_id = "run-buffer-limit"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        manager.pending_max_bytes = 32

        with self.assertRaises(AgentRunEventBacklogError):
            await manager.publish(run_id, "text_delta", {"text": "this payload exceeds the test limit"})

    async def test_stale_owner_cannot_append_after_terminal_state(self) -> None:
        manager = AgentRunManager()
        run_id = "run-fenced"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        with self.Session() as db:
            run = db.get(AgentRun, run_id)
            assert run is not None
            run.status = AgentRunStatus.CANCELLED
            run.owner_id = ""
            db.commit()

        with patch.object(manager_module, "SessionLocal", self.Session):
            await manager.publish(run_id, "text_delta", {"text": "late provider output"})
            await manager.flush(run_id)
            with self.Session() as db:
                count = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run_id).count()

        self.assertEqual(count, 0)

    def test_lease_recovery_marks_inflight_model_abandoned_and_persists_final(self) -> None:
        run_id = "run-expired-lease"
        now = datetime.now(timezone.utc)
        with self.Session() as db:
            db.add(
                AgentRun(
                    id=run_id,
                    document_id=1,
                    session_id=1,
                    user_id=1,
                    user_message_id=1,
                    client_request_id="request-expired-lease",
                    status=AgentRunStatus.RUNNING,
                    owner_id="lost-worker",
                    lease_expires_at=now - timedelta(seconds=1),
                    worker_pid=4321,
                    last_phase="model_turn_started",
                )
            )
            db.add(
                ModelCallRecord(
                    model_id=9,
                    user_id=1,
                    source=ModelCallSource.AGENT,
                    source_id=run_id,
                    status=ModelCallStatus.RUNNING,
                    usage_reported=False,
                    error_message="",
                    started_at=now - timedelta(seconds=30),
                    finished_at=None,
                )
            )
            db.add(
                AgentRunEvent(
                    run_id=run_id,
                    sequence=4,
                    event="heartbeat",
                    payload_json='{"phase":"before-recovery"}',
                )
            )
            db.commit()

            recovered = recover_expired_agent_runs(db)
            run = db.get(AgentRun, run_id)
            call = db.query(ModelCallRecord).filter(ModelCallRecord.source_id == run_id).one()
            events = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run_id).all()

        self.assertEqual(recovered, 1)
        assert run is not None
        self.assertEqual(run.status, AgentRunStatus.FAILED)
        self.assertEqual(run.owner_id, "")
        self.assertIsNone(run.lease_expires_at)
        self.assertEqual(run.last_phase, "lease_expired")
        self.assertEqual(call.status, ModelCallStatus.ABANDONED)
        self.assertIn("worker_pid=4321", call.error_message)
        self.assertEqual([event.sequence for event in events], [4, 5])
        self.assertEqual(events[-1].event, "final")
        self.assertEqual(run.event_sequence, 5)

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
