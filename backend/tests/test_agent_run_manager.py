import unittest

import app.services.agent_run_manager as manager_module
from app.services.agent_run_manager import AgentRunManager


class AgentRunManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_replays_published_event(self) -> None:
        manager = AgentRunManager()
        manager.create("run-1")
        await manager.publish("run-1", "text_delta", {"text": "hello"})

        events = manager.events_after("run-1", 0)
        event = await anext(events)
        await events.aclose()

        self.assertEqual(event.sequence, 1)
        self.assertEqual(event.event, "text_delta")
        self.assertEqual(event.data, {"text": "hello"})

    async def test_emits_heartbeat_while_waiting_for_agent_output(self) -> None:
        manager = AgentRunManager()
        manager.create("run-2")
        previous_interval = manager_module.HEARTBEAT_INTERVAL_SECONDS
        manager_module.HEARTBEAT_INTERVAL_SECONDS = 0.01
        try:
            events = manager.events_after("run-2", 0)
            event = await anext(events)
            await events.aclose()
        finally:
            manager_module.HEARTBEAT_INTERVAL_SECONDS = previous_interval

        self.assertEqual(event.sequence, 0)
        self.assertEqual(event.event, "heartbeat")
        self.assertEqual(event.data["status"], "pending")
