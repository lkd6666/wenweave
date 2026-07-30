"""跨轮工具摘要只能携带语义内容，绝不能携带定位事实。

block_id 里嵌了整篇文档的哈希与字符偏移，revision 同理：任何一次编辑之后，
上一轮的全部 block_id 与 revision 都会失效（实测 `b-3983970d-13-p` 会变成
`b-a30b49ee-17-p`）。所以摘要里放的是编辑过的正文文本——它经得起编辑、且能
直接喂给 search_html 重新定位。
"""
from __future__ import annotations

import unittest

from app.services.agent_context import _tool_summary


def _edit_tool(before: str, after: str) -> dict:
    return {
        "name": "apply_html_patch",
        "status": "success",
        "activity": {
            "kind": "edit",
            "summary": "已更新 1 个排版块",
            "revision": "rev-should-not-appear",
            "targets": [{"block_id": "b-deadbeef-13-p", "tag": "p", "before": before, "after": after}],
        },
    }


class CrossTurnToolSummaryTests(unittest.TestCase):
    def test_summary_never_carries_block_ids_or_revisions(self) -> None:
        """带上它们会让模型用必然失效的坐标去提交补丁。"""
        summary = _tool_summary([_edit_tool("旧标题", "新标题")], 500)

        self.assertNotIn("b-deadbeef", summary)
        self.assertNotIn("rev-should-not-appear", summary)
        self.assertNotIn("revision=", summary)

    def test_summary_carries_the_edited_text_so_the_model_can_research(self) -> None:
        summary = _tool_summary([_edit_tool("旧标题", "新标题")], 500)

        self.assertIn("新标题", summary)
        self.assertIn("apply_html_patch", summary)

    def test_read_only_tools_keep_their_plain_summary(self) -> None:
        summary = _tool_summary(
            [{"name": "search_html", "status": "success", "activity": {"kind": "search", "summary": "找到 3 个候选排版块"}}],
            500,
        )

        self.assertIn("search_html", summary)
        self.assertIn("找到 3 个候选排版块", summary)

    def test_failed_tool_keeps_its_status(self) -> None:
        summary = _tool_summary(
            [{"name": "apply_html_patch", "status": "error", "result": "错误：文档已变化"}],
            500,
        )

        self.assertIn("error", summary)
        self.assertIn("文档已变化", summary)

    def test_summary_respects_the_token_budget(self) -> None:
        tools = [_edit_tool("旧" * 200, "新" * 200) for _ in range(4)]

        summary = _tool_summary(tools, 20)

        from app.services.token_budget import estimate_tokens

        self.assertLessEqual(estimate_tokens(summary), 21)

    def test_non_list_input_is_tolerated(self) -> None:
        self.assertEqual(_tool_summary(None, 100), "")
        self.assertEqual(_tool_summary("not a list", 100), "")


if __name__ == "__main__":
    unittest.main()
