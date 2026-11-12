import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.routes import chat
from app.services.retry_policy import publish_retry


class CompactionRetryStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_retry_progress_then_result_with_owned_session(self):
        entry = chat.compact_chat_context
        db = MagicMock()
        db.get.return_value = SimpleNamespace(id=12)
        async def compact(*args):
            self.assertIs(args[3], db)
            self.assertIs(args[4], False)
            await publish_retry({'event': 'retry_status', 'data': {'phase': 'waiting'}})
            return {'state': 'compacted', 'used_tokens': 1234}
        with patch.object(chat, 'SessionLocal') as factory, patch.object(chat, 'compact_chat_context', compact):
            factory.return_value.__enter__.return_value = db
            response = await entry(1, SimpleNamespace(), SimpleNamespace(id=12), MagicMock(), True)
            events = [event async for event in response.body_iterator]
            self.assertEqual([event['event'] for event in events], ['retry_status', 'context_stats'])
            self.assertIn('1234', events[-1]['data'])
            factory.return_value.__exit__.assert_called_once()

    async def test_disconnect_cancels_compaction_before_commit(self):
        entry = chat.compact_chat_context
        cancelled = asyncio.Event()
        async def compact(*args):
            try:
                await publish_retry({'event': 'retry_status', 'data': {'phase': 'waiting'}})
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch.object(chat, 'SessionLocal') as factory, patch.object(chat, 'compact_chat_context', compact):
            response = await entry(1, SimpleNamespace(), SimpleNamespace(id=12), MagicMock(), True)
            await anext(response.body_iterator)
            await response.body_iterator.aclose()
            self.assertTrue(cancelled.is_set())
            factory.return_value.__exit__.assert_called_once()
