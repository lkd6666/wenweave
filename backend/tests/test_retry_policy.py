import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.services.retry_policy import (
    RetryPolicy, is_transient_error, retry_after_seconds, retry_async, retry_event_sink, retry_safe_read,
)


def upstream(status, headers=None, message="provider error"):
    response = httpx.Response(status, headers=headers, request=httpx.Request("POST", "https://test.invalid"))
    return httpx.HTTPStatusError(message, request=response.request, response=response)


class RetryPolicyTests(unittest.IsolatedAsyncioTestCase):
    def test_classification_preserves_nested_status_and_terminal_quota(self):
        for status in (408, 429, 500, 502, 503, 529):
            wrapped = RuntimeError("wrapped")
            wrapped.__cause__ = upstream(status)
            self.assertTrue(is_transient_error(wrapped))
        for status in (400, 401, 403, 404, 409, 413, 422):
            self.assertFalse(is_transient_error(upstream(status, {"x-should-retry": "true"})))
        for message in ("insufficient_quota", "insufficient credit", "quota exhausted", "余额不足"):
            self.assertFalse(is_transient_error(upstream(429, message=message)))
        self.assertFalse(is_transient_error(upstream(503, {"x-should-retry": "false"})))
        self.assertFalse(is_transient_error(ValueError("invalid local configuration")))
        self.assertFalse(is_transient_error(asyncio.CancelledError()))

    def test_retry_after_units_dates_and_invalid_values(self):
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        self.assertEqual(retry_after_seconds(upstream(429, {"Retry-After": "Wed, 04 Nov 2026 00:00:07 GMT"}), now=now), 7)
        self.assertEqual(retry_after_seconds(upstream(429, {"retry-after-ms": "1250"})), 1.25)
        for value in ("nan", "inf", "-3", "bad"):
            self.assertIsNone(retry_after_seconds(upstream(429, {"retry-after": value})))

    def test_jitter_is_capped_and_server_advice_is_a_floor(self):
        policy = RetryPolicy(base_seconds=2, max_delay_seconds=10)
        with patch('app.services.retry_policy.random.uniform', side_effect=lambda low, high: high):
            self.assertEqual(policy.delay(upstream(503), 30), (10, None))
            self.assertEqual(policy.delay(upstream(429, {"Retry-After": "7"}), 1), (7, 7))

    async def test_lifecycle_and_no_replay_after_success(self):
        events = []
        call = AsyncMock(side_effect=[upstream(503), "done"])
        with patch('app.services.retry_policy.asyncio.sleep', new_callable=AsyncMock):
            result = await retry_async(call, sink=events.append)
        self.assertEqual(result, "done")
        self.assertEqual(call.await_count, 2)
        self.assertEqual([e['data']['phase'] for e in events], ['waiting', 'attempting', 'recovered'])
        self.assertEqual(len({e['data']['operation_id'] for e in events}), 1)
        self.assertEqual(events[0]['data']['attempt'], 2)

    async def test_excessive_retry_after_and_elapsed_budget_do_not_retry_early(self):
        for policy, error in ((RetryPolicy(max_delay_seconds=10), upstream(429, {'Retry-After': '60'})),
                              (RetryPolicy(max_elapsed_seconds=.01), upstream(503))):
            call = AsyncMock(side_effect=error)
            events = []
            with self.assertRaises(httpx.HTTPStatusError):
                await retry_async(call, policy=policy, sink=events.append)
            self.assertEqual(call.await_count, 1)
            self.assertEqual(events[-1]['data']['phase'], 'exhausted')

    async def test_only_response_validation_is_allowed_format_repair(self):
        call = AsyncMock(side_effect=ValueError('configuration error'))
        with self.assertRaises(ValueError):
            await retry_async(call, retry_invalid=True)
        self.assertEqual(call.await_count, 1)
        call = AsyncMock(side_effect=['invalid', 'valid'])
        def parse(result):
            if result == 'invalid':
                raise RuntimeError('invalid JSON summary')
            return result
        with patch('app.services.retry_policy.asyncio.sleep', new_callable=AsyncMock):
            self.assertEqual(await retry_async(call, validate=parse, retry_invalid=True), 'valid')

    async def test_abort_during_backoff_starts_no_additional_requests(self):
        waiting = asyncio.Event()
        call = AsyncMock(side_effect=upstream(503))
        def emit(event):
            if event['data']['phase'] == 'waiting':
                waiting.set()
        task = asyncio.create_task(retry_async(call, sink=emit, policy=RetryPolicy(base_seconds=20)))
        await asyncio.wait_for(waiting.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(call.await_count, 1)

    async def test_read_uses_context_sink_and_keeps_provider_hints(self):
        events = []
        call = AsyncMock(side_effect=[upstream(429, {'retry-after-ms': '1'}), b'image'])
        with retry_event_sink(events.append), patch('app.services.retry_policy.asyncio.sleep', new_callable=AsyncMock):
            self.assertEqual(await retry_safe_read(call, tool='search_article_images'), b'image')
        self.assertEqual(events[0]['data']['scope'], 'tool_read')
        self.assertEqual(events[0]['data']['tool'], 'search_article_images')

    async def test_reporting_failure_never_replays_a_successful_request(self):
        call = AsyncMock(side_effect=[upstream(503), 'done'])
        def emit(event):
            if event['data']['phase'] == 'recovered':
                raise ConnectionError('event persistence failed')
        with patch('app.services.retry_policy.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaises(ConnectionError):
                await retry_async(call, sink=emit)
        self.assertEqual(call.await_count, 2)
