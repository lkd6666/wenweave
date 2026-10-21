import json
import unittest
from types import SimpleNamespace

from app.services.agent_run_recovery import recover_interrupted_turn, replay_agent_turn


class AgentRunRecoveryTests(unittest.TestCase):
    def test_replays_a_live_turn_without_terminalizing_the_current_output(self) -> None:
        events = [
            SimpleNamespace(event="reasoning_delta", payload_json=json.dumps({"text": "先检查版式。"})),
            SimpleNamespace(
                event="tool_call",
                payload_json=json.dumps({"id": "tool-1", "name": "read_blocks", "arguments": {"block_ids": ["p-1"]}}),
            ),
            SimpleNamespace(
                event="tool_result",
                payload_json=json.dumps(
                    {
                        "id": "tool-1",
                        "name": "read_blocks",
                        "result": "已读取目标段落。",
                        "model_input": {
                            "state": "available",
                            "content": '{"revision":"r-1","blocks":[]}',
                            "truncated": False,
                        },
                    }
                ),
            ),
            SimpleNamespace(event="text_delta", payload_json=json.dumps({"text": "正在调整标题层级"})),
        ]

        replayed = replay_agent_turn(events)

        self.assertEqual(replayed.reasoning_trace["status"], "thinking")
        self.assertEqual(replayed.tool_calls[0]["status"], "success")
        self.assertEqual(replayed.tool_calls[0]["model_input"]["state"], "available")
        self.assertEqual(replayed.tool_calls[0]["model_input"]["content"], '{"revision":"r-1","blocks":[]}')
        self.assertEqual(replayed.turn_blocks[-1]["type"], "content")
        self.assertEqual(replayed.turn_blocks[-1]["state"], "active")
        self.assertEqual(replayed.content, "正在调整标题层级")

    def test_rebuilds_timeline_and_keeps_pre_restart_output_visible(self) -> None:
        events = [
            SimpleNamespace(event="reasoning_delta", payload_json=json.dumps({"text": "先检查版式。"})),
            SimpleNamespace(
                event="tool_call",
                payload_json=json.dumps({"id": "tool-1", "name": "read_blocks", "arguments": {"block_ids": ["p-1"]}}),
            ),
            SimpleNamespace(
                event="tool_result",
                payload_json=json.dumps({"name": "read_blocks", "result": "已读取目标段落。"}),
            ),
            SimpleNamespace(event="text_delta", payload_json=json.dumps({"text": "已完成第一处调整。"})),
        ]

        recovered = recover_interrupted_turn(events, "服务已重启，未完成的 Agent 已停止。")

        self.assertEqual(recovered.reasoning_trace["content"], "先检查版式。")
        self.assertEqual(recovered.tool_calls[0]["status"], "success")
        self.assertEqual([block["type"] for block in recovered.turn_blocks], ["thought", "tool", "content"])
        self.assertEqual(recovered.turn_blocks[1]["content"], "")
        self.assertIn("已完成第一处调整。", recovered.content)
        self.assertIn("服务已重启", recovered.content)

    def test_discards_a_retried_model_turn_before_recovery(self) -> None:
        events = [
            SimpleNamespace(event="heartbeat", payload_json=json.dumps({"phase": "model_turn_started"})),
            SimpleNamespace(event="text_delta", payload_json=json.dumps({"text": "断流前的片段"})),
            SimpleNamespace(event="model_turn_retry", payload_json="{}"),
            SimpleNamespace(event="text_delta", payload_json=json.dumps({"text": "重试后的完整答复"})),
        ]

        recovered = recover_interrupted_turn(events, "服务已重启。")

        self.assertNotIn("断流前的片段", recovered.content)
        self.assertIn("重试后的完整答复", recovered.content)

    def test_matches_repeated_tool_names_by_call_id(self) -> None:
        events = [
            SimpleNamespace(
                event="tool_call",
                payload_json=json.dumps({"id": "call-a", "name": "search_session_history", "arguments": {}}),
            ),
            SimpleNamespace(
                event="tool_call",
                payload_json=json.dumps({"id": "call-b", "name": "search_session_history", "arguments": {}}),
            ),
            SimpleNamespace(
                event="tool_result",
                payload_json=json.dumps({"id": "call-a", "name": "search_session_history", "result": "已检索第一页"}),
            ),
            SimpleNamespace(
                event="tool_result",
                payload_json=json.dumps({"id": "call-b", "name": "search_session_history", "result": "错误：第二页不可用"}),
            ),
        ]

        recovered = recover_interrupted_turn(events, "服务已重启。")

        self.assertEqual(recovered.tool_calls[0]["status"], "success")
        self.assertEqual(recovered.tool_calls[0]["result"], "已检索第一页")
        self.assertEqual(recovered.tool_calls[1]["status"], "error")
        self.assertEqual(recovered.tool_calls[1]["result"], "错误：第二页不可用")

    def test_replays_runtime_context_compaction_as_a_persistable_process_block(self) -> None:
        events = [
            SimpleNamespace(
                event="tool_call",
                payload_json=json.dumps({"id": "read-1", "name": "read_blocks", "arguments": {}}),
            ),
            SimpleNamespace(
                event="context_compaction",
                payload_json=json.dumps(
                    {
                        "summary": "已保留最新工具循环，早期读取结果已整理。",
                        "original_tokens": 190_000,
                        "used_tokens": 48_000,
                        "summarized_cycles": 3,
                        "digested_cycles": 3,
                        "dropped_cycles": 0,
                        "summary_tokens": 600,
                        "durable_snapshot": True,
                    }
                ),
            ),
            SimpleNamespace(
                event="tool_result",
                payload_json=json.dumps({"id": "read-1", "name": "read_blocks", "result": "已读取正文。"}),
            ),
        ]

        replayed = replay_agent_turn(events)

        self.assertEqual([block["type"] for block in replayed.turn_blocks], ["tool", "context_compaction"])
        compaction = replayed.turn_blocks[1]["context_compaction"]
        self.assertEqual(compaction["original_tokens"], 190_000)
        self.assertEqual(compaction["used_tokens"], 48_000)
        self.assertEqual(compaction["summarized_cycles"], 3)
        self.assertTrue(compaction["durable_snapshot"])
        self.assertEqual(replayed.tool_calls[0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
