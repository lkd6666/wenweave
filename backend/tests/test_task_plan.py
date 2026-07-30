"""任务清单校验：清单只有在无歧义时才有价值。

多步排版需求（改标题 + 调间距 + 修图注 + 合规）最容易静默漏项。这些用例锁定
校验边界：空清单、缺 step、非法 status、以及同时多项 in_progress 都必须被拒绝，
而不是让模型带着一份自相矛盾的清单继续跑。
"""
from __future__ import annotations

import unittest

from app.services.chat_agent import (
    MAX_TASK_PLAN_ITEMS,
    TASK_PLAN_STATUSES,
    TASK_PLAN_STATUS_LABELS,
    normalise_task_plan,
)


class TaskPlanValidationTests(unittest.TestCase):
    def test_valid_plan_is_normalised(self) -> None:
        plan = normalise_task_plan(
            [
                {"step": "统一标题层级", "status": "done"},
                {"step": "调整段间距", "status": "in_progress"},
                {"step": "补图注", "status": "pending"},
            ]
        )

        self.assertEqual([item["status"] for item in plan], ["done", "in_progress", "pending"])
        self.assertEqual(plan[0]["step"], "统一标题层级")

    def test_whitespace_in_step_is_collapsed(self) -> None:
        plan = normalise_task_plan([{"step": "  统一\n标题层级  ", "status": "pending"}])

        self.assertEqual(plan[0]["step"], "统一 标题层级")

    def test_two_in_progress_steps_are_rejected(self) -> None:
        """两项同时进行时清单不再能指示「现在做什么」，必须报错而不是放过。"""
        with self.assertRaisesRegex(ValueError, "只能有一项"):
            normalise_task_plan(
                [
                    {"step": "改标题", "status": "in_progress"},
                    {"step": "调间距", "status": "in_progress"},
                ]
            )

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "status"):
            normalise_task_plan([{"step": "改标题", "status": "finished"}])

    def test_missing_step_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "缺少 step"):
            normalise_task_plan([{"step": "   ", "status": "pending"}])

    def test_empty_and_non_list_plans_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能为空"):
            normalise_task_plan([])
        with self.assertRaisesRegex(ValueError, "必须是数组"):
            normalise_task_plan({"step": "改标题", "status": "pending"})

    def test_oversized_plan_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "最多"):
            normalise_task_plan(
                [{"step": f"步骤 {index}", "status": "pending"} for index in range(MAX_TASK_PLAN_ITEMS + 1)]
            )

    def test_non_object_entry_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不是对象"):
            normalise_task_plan(["改标题"])

    def test_every_status_has_a_display_label(self) -> None:
        """缺标签会让前端把状态渲染成 KeyError 或空白。"""
        self.assertEqual(set(TASK_PLAN_STATUS_LABELS), TASK_PLAN_STATUSES)


if __name__ == "__main__":
    unittest.main()
