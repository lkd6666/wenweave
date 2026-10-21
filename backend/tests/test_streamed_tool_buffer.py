from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk

from app.services.chat_agent import (
    _AIMessageChunkAccumulator,
    _ModelDeltaBatcher,
    _StreamedToolCallBuffer,
    _ToolProgressTracker,
    _build_static_system_prompt_cached,
    _finalize_tool_calls,
    _message_tokens,
    _provider_message_tokens,
)


class StreamedToolCallBufferTests(unittest.TestCase):
    def test_duplicate_call_id_repair_avoids_existing_suffixed_ids(self) -> None:
        buffers = {}
        for index, call_id in enumerate(("call", "call-2", "call")):
            buffer = _StreamedToolCallBuffer(index=index)
            buffer.append({"name": "get_document_map", "id": call_id, "args": "{}"})
            buffers[index] = buffer

        response, errors = _finalize_tool_calls(AIMessage(content=""), buffers, {}, {})

        self.assertFalse(errors)
        ids = [call["id"] for call in response.tool_calls]
        self.assertEqual(ids, ["call", "call-2", "call-3"])

    def test_delta_fragments_handle_escaped_quotes_and_nested_braces(self) -> None:
        payload = {
            "html": '<section data-label="{示例}">括号 [内容] 和转义 \\" 引号</section>',
            "revision": "abc123",
            "operations": [{"kind": "replace", "value": {"nested": True}}],
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        buffer = _StreamedToolCallBuffer(index=0)
        for offset in range(0, len(encoded), 7):
            buffer.append({"args": encoded[offset : offset + 7]})

        self.assertEqual(buffer.complete_arguments(), payload)

    def test_cumulative_argument_protocol_does_not_duplicate_prefixes(self) -> None:
        payload = {"html": "<p>" + "正文" * 50 + "</p>", "revision": "r1"}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        buffer = _StreamedToolCallBuffer(index=0)
        for end in (12, 37, 83, len(encoded)):
            buffer.append({"args": encoded[:end]})

        self.assertEqual(buffer.arguments, encoded)
        self.assertEqual(buffer.complete_arguments(), payload)

    def test_incomplete_json_is_not_fully_parsed_and_complete_revision_parses_once(self) -> None:
        buffer = _StreamedToolCallBuffer(index=0)
        original_loads = json.loads
        with patch("app.services.chat_agent.json.loads", wraps=original_loads) as loads:
            buffer.append({"args": '{"html":"未结束'})
            self.assertIsNone(buffer.complete_arguments())
            self.assertEqual(loads.call_count, 0)
            buffer.append({"args": '"}'})
            self.assertEqual(buffer.complete_arguments(), {"html": "未结束"})
            self.assertEqual(buffer.complete_arguments(), {"html": "未结束"})
            self.assertEqual(loads.call_count, 1)

    def test_token_estimate_is_reused_until_arguments_change(self) -> None:
        buffer = _StreamedToolCallBuffer(index=0)
        buffer.append({"args": '{"query":"正文"}'})
        with patch("app.services.chat_agent.estimate_tokens", return_value=9) as estimate:
            self.assertEqual(buffer.estimated_tokens(), 9)
            self.assertEqual(buffer.estimated_tokens(), 9)
            self.assertEqual(estimate.call_count, 1)
            buffer.append({"args": " "})
            self.assertEqual(buffer.estimated_tokens(), 9)
            self.assertEqual(estimate.call_count, 2)

    def test_cumulative_progress_tracking_stays_constant_size(self) -> None:
        tracker = _ToolProgressTracker()
        chunk = SimpleNamespace(tool_calls=[])
        prefix = '{"html":"'
        for index in range(1, 2_001):
            arguments = prefix + ("字" * index)
            self.assertTrue(
                tracker.observe(
                    chunk,
                    [{"index": 0, "name": "replace_document" if index == 1 else "", "args": arguments}],
                )
            )
        self.assertEqual(len(tracker.signatures), 1)
        self.assertFalse(tracker.observe(chunk, [{"index": 0, "args": arguments}]))
        self.assertLess(len(repr(next(iter(tracker.signatures.values())))), 256)

    def test_fast_text_deltas_are_coalesced_without_changing_content(self) -> None:
        async def run() -> list[dict]:
            events: list[dict] = []
            batcher = _ModelDeltaBatcher(events.append, interval_seconds=60, max_chars=128)
            for _ in range(1_000):
                batcher.push("text_delta", "字")
            batcher.flush()
            await asyncio.sleep(0)
            return events

        events = asyncio.run(run())
        self.assertLessEqual(len(events), 8)
        self.assertEqual("".join(event["data"]["text"] for event in events), "字" * 1_000)

    def test_delta_timer_flushes_a_short_provider_burst(self) -> None:
        async def run() -> list[dict]:
            events: list[dict] = []
            batcher = _ModelDeltaBatcher(events.append, interval_seconds=0.001, max_chars=1_024)
            batcher.push("reasoning_delta", "短突发")
            await asyncio.sleep(0.01)
            return events

        self.assertEqual(
            asyncio.run(run()),
            [{"event": "reasoning_delta", "data": {"text": "短突发"}}],
        )

    def test_response_chunk_accumulator_preserves_text_tools_and_usage(self) -> None:
        accumulator = _AIMessageChunkAccumulator(batch_size=2)
        accumulator.add(AIMessageChunk(content="前"))
        accumulator.add(
            AIMessageChunk(
                content="后",
                tool_call_chunks=[{"name": "read_blocks", "args": '{"block_ids":[]}', "id": "call-1", "index": 0}],
            )
        )
        accumulator.add(
            AIMessageChunk(
                content="",
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                chunk_position="last",
            )
        )

        result = accumulator.build()

        assert result is not None
        self.assertEqual(result.content, "前后")
        self.assertEqual(result.tool_calls[0]["name"], "read_blocks")
        self.assertEqual(result.usage_metadata["total_tokens"], 12)
        self.assertFalse(accumulator.pending)
        self.assertFalse(accumulator.segments)


class StableTokenCacheTests(unittest.TestCase):
    def test_message_mutation_invalidates_cached_token_count(self) -> None:
        message = AIMessage(content="短内容")
        first = _message_tokens(message)
        message.content = "更长的内容" * 100
        second = _message_tokens(message)

        self.assertGreater(second, first)

    def test_provider_counting_multiplier_is_applied_after_neutral_cache(self) -> None:
        message = AIMessage(content="正文内容" * 100)
        neutral = _provider_message_tokens(message, 1.0)
        conservative = _provider_message_tokens(message, 1.5)

        self.assertGreater(conservative, neutral)

    def test_static_prompt_cache_is_keyed_by_rule_text(self) -> None:
        _build_static_system_prompt_cached.cache_clear()
        first = _build_static_system_prompt_cached("规则版本 A")
        repeated = _build_static_system_prompt_cached("规则版本 A")
        changed = _build_static_system_prompt_cached("规则版本 B")

        self.assertIs(first, repeated)
        self.assertIn("规则版本 A", first)
        self.assertIn("规则版本 B", changed)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
