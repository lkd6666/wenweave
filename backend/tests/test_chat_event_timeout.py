import asyncio
import unittest
from unittest.mock import patch

from app.api.routes.chat import _is_context_limit_error, _iterate_agent_events_with_timeout, _settle_terminal_timeline


class AgentEventTimeoutTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
