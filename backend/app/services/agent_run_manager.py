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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, AsyncIterator
from uuid import uuid4

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
WORKER_ID = settings.INSTANCE_ID.strip() or f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"


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


@dataclass
class LiveAgentRun:
    run_id: str
    status: str = "pending"
    events: list[RunEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    cancel_watch_task: asyncio.Task[None] | None = None
    started: bool = False
    cancel_requested: bool = False
    last_event_at: float = field(default_factory=monotonic)


class AgentRunManager:
    def __init__(self) -> None:
        self._runs: dict[str, LiveAgentRun] = {}
        self.worker_id = WORKER_ID
        self.lease_seconds = max(5, int(settings.CHAT_AGENT_RUN_LEASE_SECONDS))
        self.local_event_limit = max(8, int(settings.CHAT_AGENT_RUN_LOCAL_EVENT_LIMIT))

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

    def _persist_event(self, run_id: str, event: str, data: dict[str, Any], *, force: bool) -> int | None:
        payload_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
        now = _utcnow()
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
            if run is None:
                return None
            if not force and run.owner_id != self.worker_id:
                return None
            run.event_sequence = int(run.event_sequence or 0) + 1
            sequence = run.event_sequence
            db.add(AgentRunEvent(run_id=run_id, sequence=sequence, event=event, payload_json=payload_json))
            if run.owner_id == self.worker_id and _status_value(run.status) not in TERMINAL_STATUSES:
                run.heartbeat_at = now
                run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            db.commit()
            return sequence

    async def publish(self, run_id: str, event: str, data: dict[str, Any], *, force: bool = False) -> None:
        run = self._runs.get(run_id)
        if run is None and not force:
            return
        sequence = await asyncio.to_thread(self._persist_event, run_id, event, data, force=force)
        if sequence is None:
            if not force:
                logger.warning("agent_run_event_rejected run=%s event=%s", run_id, event)
            return
        if run is None:
            return
        async with run.condition:
            run.events.append(RunEvent(sequence=sequence, event=event, data=data))
            if len(run.events) > self.local_event_limit:
                del run.events[: len(run.events) - self.local_event_limit]
            run.last_event_at = monotonic()
            run.condition.notify_all()

    def _release_owner(self, run_id: str) -> None:
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
            if run is None or run.owner_id != self.worker_id:
                return
            if _status_value(run.status) in TERMINAL_STATUSES:
                run.owner_id = ""
                run.lease_expires_at = None
                db.commit()

    async def mark_terminal(self, run_id: str, status: str) -> None:
        run = self._runs.get(run_id)
        if run:
            async with run.condition:
                run.status = status
                run.condition.notify_all()
            if run.cancel_watch_task and not run.cancel_watch_task.done():
                run.cancel_watch_task.cancel()
        await asyncio.to_thread(self._release_owner, run_id)

    async def mark_waiting(self, run_id: str) -> None:
        """Stop local execution while retaining the durable run for a reply."""
        run = self._runs.get(run_id)
        if run:
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
                events.append(RunEvent(sequence=row.sequence, event=row.event, data=data if isinstance(data, dict) else {}))
            return events, _status_value(run.status)

    async def events_after(self, run_id: str, after: int) -> AsyncIterator[RunEvent]:
        """Replay durable events from any worker and heartbeat while waiting."""
        cursor = max(0, after)
        last_heartbeat = monotonic()
        while True:
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
