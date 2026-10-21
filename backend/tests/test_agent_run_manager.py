import asyncio
import json
import unittest
import threading
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

    async def test_terminal_and_waiting_replay_drains_all_database_pages(self) -> None:
        statuses = (AgentRunStatus.COMPLETED, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED, AgentRunStatus.WAITING_FOR_INPUT)
        count = manager_module.EVENT_PAGE_SIZE * 2 + 7
        for status in statuses:
            for local in (False, True):
                with self.subTest(status=status, local=local):
                    manager = AgentRunManager()
                    run_id = f"run-pages-{status.value}-{local}"
                    self._persist_run(manager, run_id, status)
                    if local:
                        # The local lifecycle notification may lag the transaction.
                        manager.create(run_id).status = "running"
                    final_event = "user_question" if status == AgentRunStatus.WAITING_FOR_INPUT else "final"
                    with self.Session() as db:
                        db.add_all([
                            AgentRunEvent(run_id=run_id, sequence=index, event=final_event if index == count else "text_delta",
                                          payload_json=json.dumps({"text": str(index)}))
                            for index in range(1, count + 1)
                        ])
                        db.commit()
                    with patch.object(manager_module, "SessionLocal", self.Session):
                        async def collect():
                            return [item async for item in manager.events_after(run_id, 0)]
                        received = await asyncio.wait_for(collect(), 2)
                    self.assertEqual([item.sequence for item in received], list(range(1, count + 1)))
                    self.assertEqual(received[-1].event, final_event)

    async def test_active_run_drains_backlog_before_waiting_for_live_events(self) -> None:
        manager = AgentRunManager()
        run_id = "run-active-pages"
        self._persist_run(manager, run_id)
        manager.create(run_id).status = "running"
        count = manager_module.EVENT_PAGE_SIZE + 5
        with self.Session() as db:
            db.add_all([
                AgentRunEvent(run_id=run_id, sequence=index, event="tool_call", payload_json="{}")
                for index in range(1, count + 1)
            ])
            db.commit()
        with patch.object(manager_module, "SessionLocal", self.Session):
            stream = manager.events_after(run_id, 0)
            try:
                received = [await asyncio.wait_for(anext(stream), 1) for _ in range(count)]
            finally:
                await stream.aclose()
        self.assertEqual([item.sequence for item in received], list(range(1, count + 1)))

    async def test_local_subscribers_share_committed_events_without_repolling(self) -> None:
        manager = AgentRunManager()
        run_id = "run-shared-durable"
        manager.create(run_id)
        self._persist_run(manager, run_id)

        with (
            patch.object(manager_module, "SessionLocal", self.Session),
            patch.object(manager, "_load_events", wraps=manager._load_events) as load_events,
        ):
            streams = [manager.events_after(run_id, 0) for _ in range(2)]
            waiting = [asyncio.create_task(anext(stream)) for stream in streams]
            for _ in range(50):
                if load_events.call_count >= 2:
                    break
                await asyncio.sleep(0.002)
            await manager.publish(run_id, "tool_call", {"id": "shared", "name": "read_blocks"})
            received = await asyncio.gather(*(asyncio.wait_for(task, 0.2) for task in waiting))
            await asyncio.gather(*(stream.aclose() for stream in streams))

        self.assertEqual(load_events.call_count, 2)
        self.assertEqual([event.sequence for event in received], [1, 1])
        self.assertEqual([event.data["id"] for event in received], ["shared", "shared"])

    async def test_question_transaction_can_notify_local_stream_without_duplicate_insert(self) -> None:
        manager = AgentRunManager()
        run_id = "run-atomic-question"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        payload = {
            "id": "question-1",
            "run_id": run_id,
            "question": "请选择",
            "timeout_at": "2026-09-22T08:02:00Z",
        }

        with (
            patch.object(manager_module, "SessionLocal", self.Session),
            patch.object(manager, "_load_events", wraps=manager._load_events) as load_events,
        ):
            stream = manager.events_after(run_id, 0)
            waiting = asyncio.create_task(anext(stream))
            for _ in range(50):
                local_run = manager.get(run_id)
                if load_events.call_count >= 1 and local_run is not None and local_run.condition._waiters:
                    break
                await asyncio.sleep(0.002)
            with self.Session() as db:
                run = db.get(AgentRun, run_id)
                assert run is not None
                db.add(
                    AgentRunEvent(
                        run_id=run_id,
                        sequence=1,
                        event="user_question",
                        payload_json=json.dumps(payload),
                    )
                )
                run.event_sequence = 1
                run.status = AgentRunStatus.WAITING_FOR_INPUT
                db.commit()
            await manager.notify_persisted_event(run_id, 1, "user_question", payload)
            await manager.mark_waiting(run_id)
            received = await asyncio.wait_for(waiting, 0.2)
            await stream.aclose()
            with self.Session() as db:
                event_count = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run_id).count()

        self.assertEqual(received.sequence, 1)
        self.assertEqual(received.event, "user_question")
        self.assertEqual(received.data, payload)
        self.assertEqual(event_count, 1)

    async def test_large_committed_event_bypasses_memory_cache_and_replays_from_database(self) -> None:
        manager = AgentRunManager()
        run_id = "run-large-durable"
        manager.create(run_id)
        self._persist_run(manager, run_id)

        with (
            patch.object(manager_module, "SessionLocal", self.Session),
            patch.object(manager_module, "LOCAL_DURABLE_EVENT_MAX_BYTES", 32),
            patch.object(manager, "_load_events", wraps=manager._load_events) as load_events,
        ):
            stream = manager.events_after(run_id, 0)
            waiting = asyncio.create_task(anext(stream))
            for _ in range(50):
                if load_events.call_count >= 1:
                    break
                await asyncio.sleep(0.002)
            await manager.publish(run_id, "tool_call", {"id": "large", "payload": "x" * 200})
            received = await asyncio.wait_for(waiting, 0.2)
            await stream.aclose()

        self.assertEqual(load_events.call_count, 2)
        self.assertEqual(received.sequence, 1)
        self.assertEqual(received.data["id"], "large")
        self.assertEqual(manager.get(run_id).durable_events, [])

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

    async def test_subscription_flushes_older_pending_text_before_live_fragments(self) -> None:
        manager = AgentRunManager()
        manager.flush_interval_seconds = 10
        run_id = "run-pending-prefix"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        with patch.object(manager_module, "SessionLocal", self.Session):
            await manager.publish(run_id, "text_delta", {"text": "older prefix"})
            stream = manager.events_after(run_id, 0)
            try:
                first = await asyncio.wait_for(anext(stream), 1)
                await manager.publish(run_id, "text_delta", {"text": "new fragment"})
                second = await asyncio.wait_for(anext(stream), 1)
            finally:
                await stream.aclose()
                await manager.flush(run_id)
        self.assertEqual(first.data, {"text": "older prefix"})
        self.assertGreater(first.sequence, 0)
        self.assertEqual(second.sequence, 0)
        self.assertEqual(second.data["text"], "new fragment")

    async def test_committed_tool_boundary_precedes_newer_realtime_text(self) -> None:
        manager = AgentRunManager()
        manager.flush_interval_seconds = 10
        run_id = "run-tool-order"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        with patch.object(manager_module, "SessionLocal", self.Session):
            stream = manager.events_after(run_id, 0)
            waiting = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            await manager.publish(run_id, "text_delta", {"text": "before tool"})
            first = await asyncio.wait_for(waiting, 1)
            await manager.publish(run_id, "tool_call", {"id": "call-1", "name": "read_blocks"})
            await manager.publish(run_id, "text_delta", {"text": "after tool"})
            try:
                received = [first] + [await asyncio.wait_for(anext(stream), 1) for _ in range(3)]
            finally:
                await stream.aclose()
                await manager.flush(run_id)
        self.assertEqual([item.event for item in received], ["text_delta", "text_delta", "tool_call", "text_delta"])
        self.assertGreater(received[1].sequence, 0)
        self.assertEqual(received[-1].data["text"], "after tool")

    async def test_slow_subscriber_recovers_missing_local_fragments_from_database(self) -> None:
        manager = AgentRunManager()
        manager.flush_interval_seconds = 10
        manager.local_event_limit = 8
        run_id = "run-fragment-gap"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        with patch.object(manager_module, "SessionLocal", self.Session):
            await manager.publish(run_id, "tool_call", {"id": "first"})
            stream = manager.events_after(run_id, 0)
            try:
                await asyncio.wait_for(anext(stream), 1)
                for index in range(20):
                    await manager.publish(run_id, "text_delta", {"text": f"{index},"})
                recovered = await asyncio.wait_for(anext(stream), 1)
            finally:
                await stream.aclose()
                await manager.flush(run_id)
        self.assertGreater(recovered.sequence, 0)
        self.assertNotIn("_transient", recovered.data)
        self.assertEqual(recovered.data["text"], "".join(f"{index}," for index in range(20)))

    async def test_durable_replay_does_not_forward_the_same_local_fragments_again(self) -> None:
        manager = AgentRunManager()
        manager.flush_interval_seconds = 10
        run_id = "run-durable-first"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        with patch.object(manager_module, "SessionLocal", self.Session):
            await manager.publish(run_id, "tool_call", {"id": "first"})
            stream = manager.events_after(run_id, 0)
            try:
                await asyncio.wait_for(anext(stream), 1)
                await manager.publish(run_id, "text_delta", {"text": "committed text"})
                await manager.flush(run_id)
                durable = await asyncio.wait_for(anext(stream), 1)
                await manager.publish(run_id, "text_delta", {"text": "fresh text"})
                transient = await asyncio.wait_for(anext(stream), 1)
            finally:
                await stream.aclose()
                await manager.flush(run_id)
        self.assertGreater(durable.sequence, 0)
        self.assertEqual(durable.data["text"], "committed text")
        self.assertEqual(transient.sequence, 0)
        self.assertEqual(transient.data["text"], "fresh text")

    async def test_critical_event_waits_for_an_in_flight_background_batch_commit(self) -> None:
        manager = AgentRunManager()
        manager.flush_interval_seconds = 0.01
        run_id = "run-background-order"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        started = threading.Event()
        release = threading.Event()
        original = manager._persist_events

        def slow_persist(run_id, pending, *, force):
            if pending[0].event == "text_delta":
                started.set()
                if not release.wait(2):
                    raise TimeoutError("Test write was not released")
            return original(run_id, pending, force=force)

        with patch.object(manager_module, "SessionLocal", self.Session), patch.object(manager, "_persist_events", side_effect=slow_persist):
            await manager.publish(run_id, "text_delta", {"text": "before tool"})
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            boundary = asyncio.create_task(manager.publish(run_id, "tool_call", {"id": "ordered"}))
            try:
                await asyncio.sleep(0.02)
                self.assertFalse(boundary.done())
            finally:
                release.set()
                await asyncio.wait_for(boundary, 1)
            persisted, _ = manager._load_events(run_id, 0)
        self.assertEqual([event.event for event in persisted], ["text_delta", "tool_call"])

    async def test_cancelling_a_flush_keeps_its_ordering_lock_until_commit(self) -> None:
        manager = AgentRunManager()
        manager.flush_interval_seconds = 10
        run_id = "run-cancelled-flush"
        manager.create(run_id)
        self._persist_run(manager, run_id)
        started = threading.Event()
        release = threading.Event()
        original = manager._persist_events

        def slow_persist(run_id, pending, *, force):
            if pending[0].event == "text_delta":
                started.set()
                if not release.wait(2):
                    raise TimeoutError("Test write was not released")
            return original(run_id, pending, force=force)

        with patch.object(manager_module, "SessionLocal", self.Session), patch.object(manager, "_persist_events", side_effect=slow_persist):
            await manager.publish(run_id, "text_delta", {"text": "must commit first"})
            flush = asyncio.create_task(manager.flush(run_id))
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            flush.cancel()
            boundary = asyncio.create_task(manager.publish(run_id, "tool_call", {"id": "after cancellation"}))
            try:
                await asyncio.sleep(0.02)
                self.assertFalse(boundary.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(flush, 1)
                await asyncio.wait_for(boundary, 1)
            persisted, _ = manager._load_events(run_id, 0)
        self.assertEqual([event.event for event in persisted], ["text_delta", "tool_call"])
        self.assertEqual(manager.get(run_id).committed_local_id, 1)

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

    async def test_tool_result_context_stats_are_not_coalesced(self) -> None:
        manager = AgentRunManager()
        run_id = "run-tool-context-stats"
        manager.create(run_id)
        self._persist_run(manager, run_id)

        with patch.object(manager_module, "SessionLocal", self.Session):
            await manager.publish(
                run_id,
                "context_stats",
                {"state": "tool_result_context", "tool_call_id": "call-1", "used_tokens": 100},
            )
            await manager.publish(
                run_id,
                "context_stats",
                {"state": "tool_result_context", "tool_call_id": "call-2", "used_tokens": 200},
            )
            await manager.flush(run_id)
            with self.Session() as db:
                rows = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run_id).order_by(AgentRunEvent.sequence).all()

        self.assertEqual([json.loads(row.payload_json)["tool_call_id"] for row in rows], ["call-1", "call-2"])

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

            with patch("app.services.wechat_compliance.get_official_compliance_engine", side_effect=AssertionError("Unexpected automatic check")) as checker:
                recovered = recover_expired_agent_runs(db)
            checker.assert_not_called()
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
        self.assertIsNone(json.loads(events[-1].payload_json)["compliance"])
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

    async def test_control_watch_polls_cancellation_but_renews_lease_every_ten_seconds(self) -> None:
        manager = AgentRunManager()
        manager.lease_renew_interval_seconds = 10.0
        manager.create("run-control-frequency")
        renew_flags: list[bool] = []

        def read_control(_run_id: str, *, renew_lease: bool = False):
            renew_flags.append(renew_lease)
            return (len(renew_flags) >= 42, False)

        async def no_wait(_delay: float) -> None:
            return None

        monotonic_values = [0.0, *(index * 0.5 for index in range(1, 43))]
        with (
            patch.object(manager, "_read_control", side_effect=read_control),
            patch.object(manager_module.asyncio, "sleep", side_effect=no_wait),
            patch.object(manager_module, "monotonic", side_effect=monotonic_values),
        ):
            await manager._watch_control("run-control-frequency")

        self.assertEqual(len(renew_flags), 42)
        self.assertEqual(sum(renew_flags), 2)
        self.assertLessEqual(sum(renew_flags) / len(renew_flags), 0.1)
