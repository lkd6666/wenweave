import json
import unittest
from types import SimpleNamespace

from app.services.agent_run_recovery import recover_interrupted_turn


class AgentRunRecoveryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
