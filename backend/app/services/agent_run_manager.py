"""进程内 Agent 事件缓冲与订阅管理。

模型流不依赖单个 SSE 客户端：浏览器断开后后台任务继续执行，重新连接可从事件序号
继续读取。运行终态及助手消息由数据库保存，服务重启导致的未完成运行由路由层明确
标记为失败，而不会静默重复执行工具。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, AsyncIterator


TERMINAL_STATUSES = {"completed", "cancelled", "failed"}
HEARTBEAT_INTERVAL_SECONDS = 10


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
    started: bool = False
    cancel_requested: bool = False
    last_event_at: float = field(default_factory=monotonic)


class AgentRunManager:
    def __init__(self) -> None:
        self._runs: dict[str, LiveAgentRun] = {}

    def create(self, run_id: str) -> LiveAgentRun:
        run = LiveAgentRun(run_id=run_id)
        self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> LiveAgentRun | None:
        return self._runs.get(run_id)

    def set_task(self, run_id: str, task: asyncio.Task[None]) -> None:
        run = self._runs.get(run_id)
        if run:
            run.task = task

    def mark_started(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run:
            return False
        run.started = True
        run.status = "running"
        return run.cancel_requested

    async def publish(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        async with run.condition:
            run.events.append(RunEvent(sequence=len(run.events) + 1, event=event, data=data))
            run.last_event_at = monotonic()
            run.condition.notify_all()

    async def mark_terminal(self, run_id: str, status: str) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        async with run.condition:
            run.status = status
            run.condition.notify_all()

    def request_cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run or run.status in TERMINAL_STATUSES:
            return False
        run.cancel_requested = True
        run.status = "cancelling"
        if run.started and run.task and not run.task.done():
            run.task.cancel()
        return True

    async def events_after(self, run_id: str, after: int) -> AsyncIterator[RunEvent]:
        """从 ``after`` 的后一条开始等待并回放事件，空闲时发送应用层心跳。"""
        run = self._runs.get(run_id)
        if not run:
            return

        cursor = max(0, after)
        while True:
            heartbeat = False
            async with run.condition:
                pending = [item for item in run.events if item.sequence > cursor]
                terminal = run.status in TERMINAL_STATUSES
                if not pending and not terminal:
                    try:
                        await asyncio.wait_for(run.condition.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
                    except TimeoutError:
                        heartbeat = True

            if heartbeat:
                yield RunEvent(
                    sequence=0,
                    event="heartbeat",
                    data={
                        "status": run.status,
                        "idle_seconds": max(0, round(monotonic() - run.last_event_at)),
                    },
                )
                continue

            for item in pending:
                cursor = item.sequence
                yield item
            if terminal:
                return


agent_run_manager = AgentRunManager()
