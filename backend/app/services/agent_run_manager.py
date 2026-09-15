"""Shared Agent run ownership plus bounded local SSE acceleration.

The database is the source of truth for run ownership and replayable events.
The in-process cache only reduces local notification latency; another worker can
always stream the same run without mistaking it for a restarted task.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, AsyncIterator, Iterable
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_run_event import AgentRunEvent


logger = logging.getLogger(__name__)
settings = get_settings()
TERMINAL_STATUSES = {"completed", "cancelled", "failed"}
WAITING_STATUSES = {"waiting_for_input"}
HEARTBEAT_INTERVAL_SECONDS = 10
EVENT_POLL_INTERVAL_SECONDS = 0.5
EVENT_PAGE_SIZE = 256
EVENT_SEQUENCE_RETRY_ATTEMPTS = 3


def _build_worker_id(instance_id: str) -> str:
    """Return a process-unique owner ID, even when one instance label is shared."""
    instance_label = instance_id.strip() or socket.gethostname()
    return f"{instance_label[:96]}:{os.getpid()}:{uuid4()}"


WORKER_ID = _build_worker_id(settings.INSTANCE_ID)
ACTIVE_STATUSES = {"pending", "running", "cancelling"}
COALESCIBLE_EVENTS = {"reasoning_delta", "text_delta", "context_stats"}
TERMINAL_EVENT_NAMES = {"error", "final"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _status_value(value: AgentRunStatus | str) -> str:
    return value.value if isinstance(value, AgentRunStatus) else str(value)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass
class RunEvent:
    sequence: int
    event: str
    data: dict[str, Any]
    # Local-only sequence for immediate, non-durable token delivery. It is
    # deliberately not sent as an SSE event ID because MySQL later stores a
    # compressed replacement event with a different durable sequence.
    local_id: int = 0
    occurred_at: datetime = field(default_factory=_utcnow)


@dataclass
class PendingRunEvent:
    event: str
    data: dict[str, Any]
    payload_bytes: int


class AgentRunEventBacklogError(RuntimeError):
    """Raised before a stalled persistence path can consume unbounded memory."""


@dataclass
class LiveAgentRun:
    run_id: str
    status: str = "pending"
    events: list[RunEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    cancel_watch_task: asyncio.Task[None] | None = None
    flush_task: asyncio.Task[None] | None = None
    eviction_task: asyncio.Task[None] | None = None
    pending_events: list[PendingRunEvent] = field(default_factory=list)
    pending_bytes: int = 0
    pending_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    flush_error: BaseException | None = None
    next_local_event_id: int = 1
    started: bool = False
    cancel_requested: bool = False
    last_event_at: float = field(default_factory=monotonic)


class AgentRunManager:
    def __init__(self) -> None:
        self._runs: dict[str, LiveAgentRun] = {}
        self.worker_id = WORKER_ID
        self.lease_seconds = max(5, int(settings.CHAT_AGENT_RUN_LEASE_SECONDS))
        self.local_event_limit = max(8, int(settings.CHAT_AGENT_RUN_LOCAL_EVENT_LIMIT))
        self.flush_interval_seconds = max(0.01, float(settings.CHAT_AGENT_EVENT_FLUSH_INTERVAL_SECONDS))
        self.flush_max_bytes = max(256, int(settings.CHAT_AGENT_EVENT_FLUSH_MAX_BYTES))
        self.pending_max_bytes = max(self.flush_max_bytes, int(settings.CHAT_AGENT_EVENT_PENDING_MAX_BYTES))
        self.local_ttl_seconds = max(1, int(settings.CHAT_AGENT_RUN_LOCAL_TTL_SECONDS))

    def create(self, run_id: str) -> LiveAgentRun:
        run = self._runs.get(run_id)
        if run is None:
            run = LiveAgentRun(run_id=run_id)
            self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> LiveAgentRun | None:
        return self._runs.get(run_id)

    def set_task(self, run_id: str, task: asyncio.Task[None]) -> None:
        self.create(run_id).task = task

    def _claim_started(self, run_id: str) -> bool | None:
        """Claim a pending run. ``None`` means another live worker owns it."""
        now = _utcnow()
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
            if run is None or _status_value(run.status) in TERMINAL_STATUSES | WAITING_STATUSES:
                return None
            lease_expires_at = _as_utc(run.lease_expires_at)
            has_live_foreign_owner = bool(
                run.owner_id
                and run.owner_id != self.worker_id
                and lease_expires_at is not None
                and lease_expires_at > now
            )
            if has_live_foreign_owner:
                return None
            # Never silently resume an expired already-running graph. Recovery
            # persists its checkpoint and finishes it as failed instead.
            if run.owner_id and run.owner_id != self.worker_id and _status_value(run.status) != "pending":
                return None
            cancelled = _status_value(run.status) == "cancelling" or run.cancel_requested_at is not None
            run.owner_id = self.worker_id
            run.worker_pid = os.getpid()
            run.last_phase = "cancelling" if cancelled else "starting"
            run.last_progress_at = now
            run.heartbeat_at = now
            run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            run.status = AgentRunStatus.CANCELLING if cancelled else AgentRunStatus.RUNNING
            db.commit()
            return cancelled

    async def mark_started(self, run_id: str) -> bool | None:
        run = self.create(run_id)
        if run.started:
            return run.cancel_requested
        cancelled = await asyncio.to_thread(self._claim_started, run_id)
        if cancelled is None:
            return None
        run.started = True
        run.cancel_requested = bool(cancelled)
        run.status = "cancelling" if cancelled else "running"
        if run.cancel_watch_task is None or run.cancel_watch_task.done():
            run.cancel_watch_task = asyncio.create_task(self._watch_control(run_id))
        return bool(cancelled)

    def _read_control(self, run_id: str) -> tuple[bool, bool] | None:
        now = _utcnow()
        with SessionLocal() as db:
            run = db.get(AgentRun, run_id)
            if run is None:
                return None
            status = _status_value(run.status)
            if status in TERMINAL_STATUSES | WAITING_STATUSES:
                return True, False
            if run.owner_id == self.worker_id:
                run.heartbeat_at = now
                run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                db.commit()
            return False, status == "cancelling" or run.cancel_requested_at is not None

    async def _watch_control(self, run_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(EVENT_POLL_INTERVAL_SECONDS)
                control = await asyncio.to_thread(self._read_control, run_id)
                if control is None:
                    return
                terminal, cancelled = control
                run = self._runs.get(run_id)
                if run is None or terminal:
                    return
                if cancelled:
                    run.cancel_requested = True
                    run.status = "cancelling"
                    if run.task and not run.task.done():
                        run.task.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the task continues and publish still renews the lease.
            logger.exception("agent_run_control_watch_failed run=%s", run_id)

    @staticmethod
    def _payload_bytes(data: dict[str, Any]) -> int:
        return len(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))

    @staticmethod
    def _is_event_sequence_collision(exc: IntegrityError) -> bool:
        """Whether a concurrent writer won this run's next durable sequence."""
        detail = str(getattr(exc, "orig", exc)).lower()
        return "uq_agent_run_events_run_sequence" in detail or (
            "1062" in detail and "agent_run_events" in detail and "sequence" in detail
        )

    def _persist_events_once(
        self,
        run_id: str,
        events: Iterable[PendingRunEvent],
        *,
        force: bool,
    ) -> list[RunEvent] | None:
        pending = list(events)
        if not pending:
            return []
        now = _utcnow()
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
            if run is None:
                return None
            status = _status_value(run.status)
            terminal_events_only = all(item.event in TERMINAL_EVENT_NAMES for item in pending)
            if not force:
                if run.owner_id != self.worker_id:
                    return None
                if status not in ACTIVE_STATUSES and not (status in TERMINAL_STATUSES and terminal_events_only):
                    return None
            # ``event_sequence`` is the allocation cursor, but deployments
            # that introduced it after runs were already active can have
            # durable events ahead of that cursor.  The parent row lock
            # serializes current writers; the event-table high-water mark also
            # makes the allocator repair any older cursor before inserting.
            durable_sequence = (
                db.query(AgentRunEvent.sequence)
                .filter(AgentRunEvent.run_id == run_id)
                .order_by(AgentRunEvent.sequence.desc())
                .limit(1)
                .scalar()
            )
            sequence = max(int(run.event_sequence or 0), int(durable_sequence or 0))
            if sequence != int(run.event_sequence or 0):
                logger.warning(
                    "agent_run_event_sequence_repaired run=%s cursor=%s durable=%s",
                    run_id,
                    run.event_sequence,
                    durable_sequence,
                )
            persisted: list[RunEvent] = []
            for item in pending:
                sequence += 1
                db.add(
                    AgentRunEvent(
                        run_id=run_id,
                        sequence=sequence,
                        event=item.event,
                        payload_json=json.dumps(item.data, ensure_ascii=False, separators=(",", ":"), default=str),
                        created_at=now,
                    )
                )
                persisted.append(RunEvent(sequence=sequence, event=item.event, data=item.data, occurred_at=now))
            run.event_sequence = sequence
            last_event = pending[-1]
            phase = last_event.event
            if last_event.event == "heartbeat":
                phase = str(last_event.data.get("phase") or phase)
            run.last_phase = phase[:64]
            run.last_progress_at = now
            if run.owner_id == self.worker_id and status in ACTIVE_STATUSES:
                run.heartbeat_at = now
                run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            db.commit()
            return persisted

    def _persist_events(
        self,
        run_id: str,
        events: Iterable[PendingRunEvent],
        *,
        force: bool,
    ) -> list[RunEvent] | None:
        """Persist one ordered batch, rebasing only a raced sequence allocation.

        The run row lock is the normal allocator.  This retry protects a live
        request when an older worker or a misconfigured database writer bypasses
        that lock: the failed transaction is rolled back, the durable high-water
        mark is re-read, and the same event is appended at the next sequence.
        """
        pending = list(events)
        for attempt in range(1, EVENT_SEQUENCE_RETRY_ATTEMPTS + 1):
            try:
                return self._persist_events_once(run_id, pending, force=force)
            except IntegrityError as exc:
                if not self._is_event_sequence_collision(exc) or attempt >= EVENT_SEQUENCE_RETRY_ATTEMPTS:
                    raise
                logger.warning(
                    "agent_run_event_sequence_collision_retry run=%s attempt=%s/%s detail=%s",
                    run_id,
                    attempt,
                    EVENT_SEQUENCE_RETRY_ATTEMPTS,
                    str(getattr(exc, "orig", exc)).replace("\n", " ")[:240],
                )
        raise RuntimeError("unreachable event persistence retry state")

    @staticmethod
    def _merge_text_event(target: PendingRunEvent, data: dict[str, Any]) -> PendingRunEvent:
        merged_data = dict(target.data)
        merged_data["text"] = str(target.data.get("text", "")) + str(data.get("text", ""))
        return PendingRunEvent(
            event=target.event,
            data=merged_data,
            payload_bytes=AgentRunManager._payload_bytes(merged_data),
        )

    async def _queue_coalesced_event(self, run: LiveAgentRun, event: str, data: dict[str, Any]) -> None:
        payload_bytes = self._payload_bytes(data)
        async with run.pending_lock:
            if run.flush_error is not None:
                raise AgentRunEventBacklogError("Agent 事件持久化失败，已停止继续缓存") from run.flush_error
            if event in {"reasoning_delta", "text_delta"} and run.pending_events:
                previous = run.pending_events[-1]
                if previous.event == event and "text" in previous.data and "text" in data:
                    candidate = self._merge_text_event(previous, data)
                    if candidate.payload_bytes <= self.flush_max_bytes:
                        projected_bytes = run.pending_bytes - previous.payload_bytes + candidate.payload_bytes
                        if projected_bytes > self.pending_max_bytes:
                            raise AgentRunEventBacklogError(
                                f"Agent 事件待写缓冲超过 {self.pending_max_bytes} 字节，已停止本轮执行"
                            )
                        run.pending_events[-1] = candidate
                        run.pending_bytes = projected_bytes
                        if run.flush_task is None or run.flush_task.done():
                            run.flush_task = asyncio.create_task(self._flush_after_delay(run.run_id))
                        return
            if event == "context_stats" and data.get("state") != "tool_result_context":
                # Keep one snapshot but place its replacement at the tail: the
                # state is observed now, not at the time of the superseded one.
                prior_index: int | None = None
                for index in range(len(run.pending_events) - 1, -1, -1):
                    if run.pending_events[index].event == "context_stats":
                        prior_index = index
                        break
                prior_bytes = run.pending_events[prior_index].payload_bytes if prior_index is not None else 0
                projected_bytes = run.pending_bytes - prior_bytes + payload_bytes
                if projected_bytes > self.pending_max_bytes:
                    raise AgentRunEventBacklogError(
                        f"Agent 事件待写缓冲超过 {self.pending_max_bytes} 字节，已停止本轮执行"
                    )
                if prior_index is not None:
                    run.pending_events.pop(prior_index)
                run.pending_events.append(PendingRunEvent(event=event, data=data, payload_bytes=payload_bytes))
                run.pending_bytes = projected_bytes
                if run.flush_task is None or run.flush_task.done():
                    run.flush_task = asyncio.create_task(self._flush_after_delay(run.run_id))
                return
            projected_bytes = run.pending_bytes + payload_bytes
            if projected_bytes > self.pending_max_bytes:
                raise AgentRunEventBacklogError(
                    f"Agent 事件待写缓冲超过 {self.pending_max_bytes} 字节，已停止本轮执行"
                )
            run.pending_events.append(PendingRunEvent(event=event, data=data, payload_bytes=payload_bytes))
            run.pending_bytes = projected_bytes
            if run.flush_task is None or run.flush_task.done():
                run.flush_task = asyncio.create_task(self._flush_after_delay(run.run_id))

    async def _flush_after_delay(self, run_id: str) -> None:
        try:
            await asyncio.sleep(self.flush_interval_seconds)
            await self._flush_pending(run_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the next publisher turns this into a terminal failure.
            logger.exception("agent_run_event_flush_failed run=%s", run_id)
        finally:
            run = self._runs.get(run_id)
            if run is not None and run.flush_task is asyncio.current_task():
                run.flush_task = None

    async def _flush_pending(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is None:
            return
        async with run.flush_lock:
            async with run.pending_lock:
                if not run.pending_events:
                    return
                pending = run.pending_events
                run.pending_events = []
                run.pending_bytes = 0
            try:
                persisted = await asyncio.to_thread(self._persist_events, run_id, pending, force=False)
            except Exception as exc:
                async with run.pending_lock:
                    run.pending_events = [*pending, *run.pending_events]
                    run.pending_bytes = sum(item.payload_bytes for item in run.pending_events)
                    run.flush_error = exc
                raise
            if persisted is None:
                logger.warning("agent_run_event_batch_rejected run=%s count=%s", run_id, len(pending))
                return
            async with run.pending_lock:
                # A transient database failure can recover before the next
                # critical boundary. Do not poison that retry with its old
                # exception once this batch has committed successfully.
                run.flush_error = None
            await self._wake_streams(run)

    async def flush(self, run_id: str) -> None:
        """Synchronously persist queued deltas before an ordering boundary."""
        run = self._runs.get(run_id)
        if run is None:
            return
        task = run.flush_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._flush_pending(run_id)
        if run.flush_error is not None:
            raise AgentRunEventBacklogError("Agent 事件持久化失败") from run.flush_error

    async def _notify_realtime(self, run: LiveAgentRun, event: str, data: dict[str, Any]) -> None:
        """Send token fragments to local SSE clients before MySQL batching."""
        async with run.condition:
            run.events.append(
                RunEvent(
                    sequence=0,
                    event=event,
                    data={**data, "_transient": True},
                    local_id=run.next_local_event_id,
                )
            )
            run.next_local_event_id += 1
            if len(run.events) > self.local_event_limit:
                del run.events[: len(run.events) - self.local_event_limit]
            run.last_event_at = monotonic()
            run.condition.notify_all()

    async def _wake_streams(self, run: LiveAgentRun) -> None:
        """Wake local SSE polls after a durable batch becomes replayable."""
        async with run.condition:
            run.last_event_at = monotonic()
            run.condition.notify_all()

    async def publish(self, run_id: str, event: str, data: dict[str, Any], *, force: bool = False) -> None:
        run = self._runs.get(run_id)
        if run is None and not force:
            return
        if run is not None and not force and event in COALESCIBLE_EVENTS:
            await self._notify_realtime(run, event, data)
            await self._queue_coalesced_event(run, event, data)
            return
        if run is not None:
            await self.flush(run_id)
        persisted = await asyncio.to_thread(
            self._persist_events,
            run_id,
            [PendingRunEvent(event=event, data=data, payload_bytes=self._payload_bytes(data))],
            force=force,
        )
        if persisted is None:
            if not force:
                logger.warning("agent_run_event_rejected run=%s event=%s", run_id, event)
            return
        if run is None:
            return
        await self._wake_streams(run)

    def _release_owner(self, run_id: str) -> None:
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
            if run is None:
                return
            if _status_value(run.status) in TERMINAL_STATUSES:
                run.owner_id = ""
                run.lease_expires_at = None
                db.commit()

    async def _evict_after_ttl(self, run_id: str) -> None:
        await asyncio.sleep(self.local_ttl_seconds)
        run = self._runs.get(run_id)
        if run is None or run.status not in TERMINAL_STATUSES:
            return
        if run.task is not None and not run.task.done():
            return
        self._runs.pop(run_id, None)

    async def mark_terminal(self, run_id: str, status: str) -> None:
        run = self._runs.get(run_id)
        if run:
            try:
                await self.flush(run_id)
            except AgentRunEventBacklogError:
                # Terminal state has already been committed by the execution
                # path. When MySQL is unavailable, do not retain its owner or
                # local task indefinitely merely because old token deltas could
                # not be replayed; the next lease recovery can still inspect
                # the durable terminal run.
                logger.exception("agent_run_terminal_flush_failed run=%s", run_id)
            async with run.condition:
                run.status = status
                run.condition.notify_all()
            if run.cancel_watch_task and not run.cancel_watch_task.done():
                run.cancel_watch_task.cancel()
        await asyncio.to_thread(self._release_owner, run_id)
        if run and (run.eviction_task is None or run.eviction_task.done()):
            run.eviction_task = asyncio.create_task(self._evict_after_ttl(run_id))

    async def mark_waiting(self, run_id: str) -> None:
        """Stop local execution while retaining the durable run for a reply."""
        run = self._runs.get(run_id)
        if run:
            await self.flush(run_id)
            async with run.condition:
                run.status = "waiting_for_input"
                run.started = False
                run.task = None
                run.condition.notify_all()
            if run.cancel_watch_task and not run.cancel_watch_task.done():
                run.cancel_watch_task.cancel()

    def request_cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run or run.status in TERMINAL_STATUSES:
            return False
        run.cancel_requested = True
        run.status = "cancelling"
        if run.started and run.task and not run.task.done():
            run.task.cancel()
        return True

    def is_cancel_requested(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run and run.cancel_requested:
            return True
        # A cancellation can be routed to a different worker. Tool boundaries
        # must observe the durable control plane immediately instead of waiting
        # for the owner's 500 ms watcher tick.
        try:
            with SessionLocal() as db:
                persisted = db.get(AgentRun, run_id)
                if persisted is None:
                    return False
                return (
                    _status_value(persisted.status) == AgentRunStatus.CANCELLING.value
                    or persisted.cancel_requested_at is not None
                )
        except Exception:  # noqa: BLE001 - the watcher still retries control reads.
            logger.exception("agent_run_cancel_check_failed run=%s", run_id)
            return False

    def _load_events(self, run_id: str, after: int) -> tuple[list[RunEvent], str | None]:
        with SessionLocal() as db:
            run = db.get(AgentRun, run_id)
            if run is None:
                return [], None
            rows = (
                db.query(AgentRunEvent)
                .filter(AgentRunEvent.run_id == run_id, AgentRunEvent.sequence > after)
                .order_by(AgentRunEvent.sequence)
                .limit(EVENT_PAGE_SIZE)
                .all()
            )
            events: list[RunEvent] = []
            for row in rows:
                try:
                    data = json.loads(row.payload_json or "{}")
                except json.JSONDecodeError:
                    data = {"message": "运行事件损坏，已跳过"}
                events.append(
                    RunEvent(
                        sequence=row.sequence,
                        event=row.event,
                        data=data if isinstance(data, dict) else {},
                        occurred_at=_as_utc(row.created_at) or _utcnow(),
                    )
                )
            return events, _status_value(run.status)

    async def _local_events_after(
        self,
        run: LiveAgentRun,
        local_cursor: int,
    ) -> tuple[list[RunEvent], int]:
        async with run.condition:
            events = [item for item in run.events if item.local_id > local_cursor]
        if events:
            local_cursor = events[-1].local_id
        return events, local_cursor

    async def events_after(self, run_id: str, after: int) -> AsyncIterator[RunEvent]:
        """Replay durable events and immediately forward local token fragments."""
        cursor = max(0, after)
        last_heartbeat = monotonic()
        initial_run = self._runs.get(run_id)
        local_cursor = 0
        if initial_run is not None:
            # Events emitted before the subscription are replayed from MySQL.
            # Only fragments produced after it connects use the transient path.
            async with initial_run.condition:
                local_cursor = initial_run.next_local_event_id - 1
        while True:
            run = self._runs.get(run_id)
            if run is not None:
                realtime, local_cursor = await self._local_events_after(run, local_cursor)
                for item in realtime:
                    yield item
                if realtime:
                    continue
            try:
                pending, status = await asyncio.to_thread(self._load_events, run_id, cursor)
            except Exception:  # noqa: BLE001 - retry polling instead of dropping an active stream on a transient DB error.
                logger.exception("agent_run_event_poll_failed run=%s", run_id)
                pending, status = [], None
            for item in pending:
                cursor = item.sequence
                yield item
            if status in TERMINAL_STATUSES | WAITING_STATUSES:
                return
            now = monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                yield RunEvent(sequence=0, event="heartbeat", data={"status": status or "unknown", "idle_seconds": 0})
                last_heartbeat = now
            run = self._runs.get(run_id)
            if run is not None:
                try:
                    async with run.condition:
                        # Recheck under the same lock used by the publisher so
                        # a token emitted between the prior read and wait is
                        # never delayed until the polling timeout.
                        if any(item.local_id > local_cursor for item in run.events):
                            continue
                        await asyncio.wait_for(run.condition.wait(), timeout=EVENT_POLL_INTERVAL_SECONDS)
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(EVENT_POLL_INTERVAL_SECONDS)


agent_run_manager = AgentRunManager()


def cleanup_expired_agent_run_events(db, *, now: datetime | None = None) -> int:
    """Remove replay records only after their terminal run has aged out."""
    retention_seconds = max(60, int(settings.CHAT_AGENT_RUN_EVENT_RETENTION_SECONDS))
    cutoff = (now or _utcnow()) - timedelta(seconds=retention_seconds)
    terminal_run_ids = db.query(AgentRun.id).filter(
        AgentRun.status.in_(
            [AgentRunStatus.COMPLETED, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED]
        ),
        AgentRun.finished_at.is_not(None),
        AgentRun.finished_at <= cutoff,
    )
    deleted = (
        db.query(AgentRunEvent)
        .filter(AgentRunEvent.run_id.in_(terminal_run_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)
