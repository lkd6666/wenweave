"""Bounded application retries; SDK retries must stay disabled.

The caller chooses a replay-safe boundary. This module does not replay writes.
"""
from __future__ import annotations

import asyncio
import inspect
import math
import random
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any, Callable
from uuid import uuid4


_EVENT_SINK: ContextVar[Callable | None] = ContextVar("agent_retry_event_sink", default=None)
_TRANSIENT = re.compile(
    r"\b(?:408|429|500|502|503|504|529)\b|rate.?limit|overloaded|too many requests|"
    r"concurren(?:cy|t).*?(?:limit|exceed|busy)|account.*busy|timeout|timed out|"
    r"temporarily unavailable|service unavailable|bad gateway|connection (?:error|reset|aborted|refused)|"
    r"peer closed|incomplete (?:chunked|message)|end of stream|broken pipe|remoteprotocolerror|"
    r"econnreset|econnrefused|eai_again|未产生新输出|连接中断|连接重置", re.I,
)
_PERMANENT = re.compile(
    r"insufficient_quota|insufficient[_ ](?:balance|credit)|billing_hard_limit|credit balance.*low|"
    r"exceeded.*(?:monthly|daily|spending).*limit|quota.*(?:exhausted|depleted)|"
    r"(?:daily|monthly).*quota.*exceed|余额不足|欠费|额度已用尽|invalid[_ ]api[_ ]key|"
    r"context_length_exceeded|maximum context length|context window.*exceed|too many tokens", re.I,
)


def error_chain(exc: BaseException):
    seen = set()
    for _ in range(8):
        if id(exc) in seen:
            break
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__
        if exc is None:
            break


def error_status(exc: BaseException) -> int | None:
    for error in error_chain(exc):
        for obj in (error, getattr(error, "response", None)):
            value = getattr(obj, "status_code", None)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def error_headers(exc: BaseException) -> dict[str, str]:
    headers = {}
    for error in reversed(list(error_chain(exc))):
        for obj in (getattr(error, "response", None), error):
            value = getattr(obj, "headers", None)
            if hasattr(value, "items"):
                headers.update({str(k).lower(): str(v) for k, v in value.items()})
    return headers


def retry_after_seconds(exc: BaseException, *, now: datetime | None = None) -> float | None:
    headers = error_headers(exc)
    values: list[tuple[object, float]] = [(headers.get("retry-after-ms"), .001),
        (headers.get("x-ms-retry-after-ms"), .001), (headers.get("retry-after"), 1)]
    for error in error_chain(exc):
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            for item in (body, body.get("error")):
                if isinstance(item, dict):
                    values.append((item.get("retry_after"), 1))
        match = re.search(r"['\"]retry_after['\"]\s*:\s*['\"]?([0-9.]+)", str(error))
        if match:
            values.append((match.group(1), 1))
    for value, scale in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            seconds = float(value) * scale
        except (TypeError, ValueError):
            try:
                deadline = parsedate_to_datetime(str(value))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                seconds = max(0, (deadline - (now or datetime.now(timezone.utc))).total_seconds())
            except (TypeError, ValueError, OverflowError):
                continue
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    return None


def is_transient_error(exc: BaseException) -> bool:
    if not isinstance(exc, Exception):
        return False
    chain = list(error_chain(exc))
    text = " ".join(str(error) + " " + str(getattr(error, "body", "")) for error in chain)
    if _PERMANENT.search(text):
        return False
    status = error_status(exc)
    # Server advice never turns authentication/validation/conflict into replay.
    if status is not None and 400 <= status < 500 and status not in {408, 429}:
        return False
    advice = error_headers(exc).get("x-should-retry", "").lower()
    if advice == "false":
        return False
    if advice == "true":
        return True
    if status is not None:
        return status in {408, 429} or 500 <= status < 600
    if any(isinstance(error, (TimeoutError, ConnectionError)) or type(error).__name__ in {
        "APIConnectionError", "APITimeoutError", "ConnectError", "ReadError", "WriteError",
        "RemoteProtocolError", "ReadTimeout", "ConnectTimeout", "PoolTimeout",
    } for error in chain):
        return True
    return bool(_TRANSIENT.search(text))


def failure_reason(exc: BaseException) -> str:
    status = error_status(exc)
    if status is not None:
        return f"upstream_{status}"
    if any(isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower() for e in error_chain(exc)):
        return "request_timeout"
    return "connection_interrupted"


def failure_detail(reason: str) -> str:
    if reason == "upstream_429":
        return "服务限流或并发已满，等待后重新请求。"
    if reason == "invalid_summary":
        return "压缩结果格式不完整，正在重新生成摘要。"
    if "timeout" in reason:
        return "本次请求等待超时，正在重新请求。"
    if reason == "stream_empty_response":
        return "模型未返回有效输出，正在重新请求。"
    if reason.startswith("upstream_"):
        return f"上游服务暂时不可用（HTTP {reason[9:]}），正在重新请求。"
    return "连接暂时中断，正在重新请求。"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_seconds: float = 1
    max_delay_seconds: float = 60
    max_elapsed_seconds: float = 600

    def delay(self, exc: BaseException, failed_attempt: int) -> tuple[float, float | None]:
        cap = max(0, self.max_delay_seconds)
        local = min(cap, max(0, self.base_seconds) * 2 ** min(30, max(0, failed_attempt - 1)))
        # Equal jitter spreads concurrent clients; clamp after jitter as well.
        jittered = random.uniform(local / 2, local)
        advice = retry_after_seconds(exc)
        return min(cap, math.ceil(max(jittered, advice or 0) * 1000) / 1000), advice


def retry_event(*, operation_id: str, scope: str, phase: str, attempt: int,
                policy: RetryPolicy, reason: str, delay: float = 0,
                retry_after: float | None = None, **extra) -> dict[str, Any]:
    detail = failure_detail(reason)
    if phase == "exhausted":
        if extra.get("stop_reason") == "server_wait_limit":
            detail = f"服务端要求等待 {retry_after:g} 秒，超过本操作的自动等待上限，已停止自动重试。"
        elif extra.get("stop_reason") == "time_budget":
            detail = "本操作已达到重试时间预算，已停止自动重试。"
        elif extra.get("stop_reason") == "permanent_error":
            detail = "服务返回了无法自动恢复的错误，已停止自动重试。"
        else:
            detail = "本操作已达到请求次数上限，已停止自动重试。"
    return {"event": "retry_status", "data": {
        "operation_id": operation_id, "scope": scope, "phase": phase,
        "attempt": attempt, "max_attempts": policy.max_attempts,
        "remaining_attempts": max(0, policy.max_attempts - attempt),
        "delay_seconds": delay,
        "retry_at": datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + delay, timezone.utc).isoformat(),
        "retry_after_seconds": retry_after,
        "reason": reason, "detail": detail, **extra,
    }}


@contextmanager
def retry_event_sink(sink: Callable):
    token = _EVENT_SINK.set(sink)
    try:
        yield
    finally:
        _EVENT_SINK.reset(token)


async def publish_retry(event: dict, sink: Callable | None = None):
    callback = sink or _EVENT_SINK.get()
    if callback:
        result = callback(event)
        if inspect.isawaitable(result):
            await result


async def retry_async(operation: Callable, *, policy: RetryPolicy | None = None,
                      scope: str = "compaction", validate: Callable | None = None,
                      tracker_factory: Callable | None = None, sink: Callable | None = None,
                      retry_invalid: bool = False, metadata: dict | None = None):
    policy = policy or RetryPolicy()
    operation_id, started = uuid4().hex, monotonic()
    reason = "connection_interrupted"
    for attempt in range(1, policy.max_attempts + 1):
        if attempt > 1:
            await publish_retry(retry_event(operation_id=operation_id, scope=scope, phase="attempting",
                attempt=attempt, policy=policy, reason=reason, **(metadata or {})), sink)
        tracker = tracker_factory() if tracker_factory else None
        invalid = False
        try:
            response = await operation()
            if tracker:
                tracker.complete(response)
            try:
                result = validate(response) if validate else response
            except Exception:
                invalid = retry_invalid
                raise
        except BaseException as exc:
            if tracker:
                tracker.fail(exc)
            if not isinstance(exc, Exception):
                raise
            reason = "invalid_summary" if invalid else failure_reason(exc)
            retryable = invalid or is_transient_error(exc)
            delay, advice = policy.delay(exc, attempt)
            elapsed = monotonic() - started
            exhausted = (attempt >= policy.max_attempts or elapsed + delay >= policy.max_elapsed_seconds
                         or (advice is not None and advice > policy.max_delay_seconds))
            if not retryable or exhausted:
                if attempt > 1 or retryable:
                    await publish_retry(retry_event(operation_id=operation_id, scope=scope, phase="exhausted",
                        attempt=attempt, policy=policy, reason=reason, retry_after=advice,
                        stop_reason=("permanent_error" if not retryable else
                            "server_wait_limit" if advice is not None and advice > policy.max_delay_seconds else
                            "time_budget" if elapsed + delay >= policy.max_elapsed_seconds else "attempt_limit"),
                        **(metadata or {})), sink)
                raise
            await publish_retry(retry_event(operation_id=operation_id, scope=scope, phase="waiting",
                attempt=attempt + 1, policy=policy, reason=reason, delay=delay,
                retry_after=advice, **(metadata or {})), sink)
            await asyncio.sleep(delay)
            if monotonic() - started >= policy.max_elapsed_seconds:
                await publish_retry(retry_event(operation_id=operation_id, scope=scope, phase="exhausted",
                    attempt=attempt, policy=policy, reason=reason, stop_reason="time_budget", **(metadata or {})), sink)
                raise
            continue
        if attempt > 1:
            await publish_retry(retry_event(operation_id=operation_id, scope=scope, phase="recovered",
                attempt=attempt, policy=policy, reason=reason, **(metadata or {})), sink)
        return result


async def retry_safe_read(operation: Callable, *, tool: str):
    """Retry a bounded network read, never an entire write-capable tool."""
    return await retry_async(operation, scope="tool_read", metadata={"tool": tool},
        policy=RetryPolicy(base_seconds=.5, max_delay_seconds=10, max_elapsed_seconds=45))
