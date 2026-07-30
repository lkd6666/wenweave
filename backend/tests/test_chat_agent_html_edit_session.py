import unittest

from app.services.chat_agent import (
    HtmlEditSession,
    _parse_attached_template_ids,
    _short,
    build_system_prompt,
)
from app.services.html_workspace import WorkspaceError


def _patch_operations(session: HtmlEditSession, *pairs: tuple[str, str]) -> list[dict]:
    """按正文定位块，组装带 expected_hash 的补丁操作。

    这是模型真实走的链路：search_html → read_blocks → apply_html_patch。
    """
    block_ids: list[str] = []
    replacements: list[str] = []
    for text, replacement in pairs:
        results = session.search(text, limit=32)["results"]
        block_id = next(
            item["block_id"]
            for item in results
            if item["tag"] == "p" and item["text"].strip() == text
        )
        block_ids.append(block_id)
        replacements.append(replacement)

    hashes = {
        block["block_id"]: block["expected_hash"]
        for block in session.read_blocks(block_ids)["blocks"]
    }
    return [
        {
            "block_id": block_id,
            "expected_hash": hashes[block_id],
            "mode": "replace_inner",
            "html": replacement,
        }
        for block_id, replacement in zip(block_ids, replacements)
    ]


class HtmlEditSessionSafetyTests(unittest.TestCase):
    def test_attached_template_reader_parses_json_array_string(self) -> None:
        parsed = _parse_attached_template_ids("[1, 2]")

        self.assertEqual(parsed, [1, 2])

    def test_tool_activity_summary_shortener_is_available(self) -> None:
        self.assertEqual(_short("  查找\n排版块  ", 20), "查找 排版块")
        self.assertEqual(_short("abcdef", 4), "abc…")

    def test_long_document_can_be_overwritten_in_full(self) -> None:
        source = "<section>" + ("x" * 20_000) + "</section>"
        session = HtmlEditSession(source)

        summary = session.replace_document(session.document_map()["revision"], "<section>new content</section>")

        self.assertEqual(summary["operation_count"], 1)
        self.assertEqual(session.html, "<section>new content</section>")
        self.assertTrue(session.edited)

    def test_small_document_can_be_replaced_in_full(self) -> None:
        session = HtmlEditSession("")

        summary = session.replace_document(
            session.document_map()["revision"], "<section><p>new content</p></section>"
        )

        self.assertEqual(summary["operation_count"], 1)
        self.assertEqual(session.html, "<section><p>new content</p></section>")
        self.assertTrue(session.edited)

    def test_completed_edit_can_be_checkpointed_before_the_next_model_turn(self) -> None:
        checkpoints: list[str] = []
        session = HtmlEditSession("<p>old</p>", checkpoint_callback=checkpoints.append)

        session.replace_document(session.document_map()["revision"], "<p>new</p>")
        session.persist_checkpoint()

        self.assertEqual(checkpoints, ["<p>new</p>"])

    def test_cancellation_between_patch_and_checkpoint_does_not_persist_candidate(self) -> None:
        checkpoints: list[str] = []
        cancelled = False
        session = HtmlEditSession(
            "<p>old</p>",
            checkpoint_callback=checkpoints.append,
            cancel_requested=lambda: cancelled,
        )

        session.replace_document(session.document_map()["revision"], "<p>new</p>")
        cancelled = True
        session.persist_checkpoint()

        self.assertEqual(checkpoints, [])
        self.assertEqual(session.html, "<p>new</p>")

    def test_cancellation_during_patch_keeps_html_unmodified(self) -> None:
        calls = 0

        def cancellation_requested() -> bool:
            nonlocal calls
            calls += 1
            # The first fence permits workspace construction; the second is
            # immediately before assigning the candidate HTML.
            return calls >= 2

        session = HtmlEditSession("<p>old</p>", cancel_requested=cancellation_requested)

        with self.assertRaisesRegex(WorkspaceError, "正在停止"):
            session.replace_document(session.document_map()["revision"], "<p>new</p>")

        self.assertEqual(session.html, "<p>old</p>")
        self.assertFalse(session.edited)

    def test_full_replacement_requires_the_current_revision(self) -> None:
        session = HtmlEditSession("<p>old</p>")

        with self.assertRaisesRegex(WorkspaceError, "文档已变化"):
            session.replace_document("stale-revision", "<p>new</p>")

        self.assertEqual(session.html, "<p>old</p>")
        self.assertFalse(session.edited)

    def test_large_patch_can_replace_a_unique_block(self) -> None:
        session = HtmlEditSession("<p>old</p>")
        replacement = "x" * 20_000

        summary = session.patch_blocks(
            session.document_map()["revision"],
            _patch_operations(session, ("old", replacement)),
        )

        self.assertEqual(summary["operation_count"], 1)
        self.assertEqual(session.html, f"<p>{replacement}</p>")
        self.assertTrue(session.edited)

    def test_one_patch_call_updates_multiple_blocks(self) -> None:
        session = HtmlEditSession("<p>first</p><p>second</p>")

        summary = session.patch_blocks(
            session.document_map()["revision"],
            _patch_operations(session, ("first", "one"), ("second", "two")),
        )

        self.assertEqual(summary["operation_count"], 2)
        self.assertEqual(session.html, "<p>one</p><p>two</p>")

    def test_patch_is_atomic_when_one_operation_is_stale(self) -> None:
        source = "<p>first</p><p>second</p>"
        session = HtmlEditSession(source)
        operations = _patch_operations(session, ("first", "one"), ("second", "two"))
        operations[1]["expected_hash"] = "stale-hash"

        with self.assertRaisesRegex(WorkspaceError, "第 2 条补丁基于旧内容"):
            session.patch_blocks(session.document_map()["revision"], operations)

        self.assertEqual(session.html, source)
        self.assertFalse(session.edited)

    def test_repeated_text_is_patched_per_block_not_by_string_match(self) -> None:
        # 三个同文本块必须逐块定位。整篇字符串替换会一次改掉全部，
        # 这正是原 batch_replace 绕过 expected_hash 锁的风险。
        session = HtmlEditSession("<p>same</p><p>same</p><p>same</p>")
        results = [
            item for item in session.search("same", limit=32)["results"] if item["tag"] == "p"
        ]
        self.assertEqual(len(results), 3)
        target = results[1]["block_id"]
        expected_hash = next(
            block["expected_hash"] for block in session.read_blocks([target])["blocks"]
        )

        session.patch_blocks(
            session.document_map()["revision"],
            [
                {
                    "block_id": target,
                    "expected_hash": expected_hash,
                    "mode": "replace_inner",
                    "html": "updated",
                }
            ],
        )

        self.assertEqual(session.html, "<p>same</p><p>updated</p><p>same</p>")

    def test_prompt_prioritises_block_patches_over_document_replacement(self) -> None:
        prompt = build_system_prompt("测试", "<p>正文</p>")

        self.assertIn("search_html → read_blocks → apply_html_patch", prompt)
        self.assertIn("模型可自行判断", prompt)
        self.assertIn("局部补丁会显著增加风险或复杂度", prompt)

    def test_prompt_restricts_parallel_tool_calls_to_read_only_tools(self) -> None:
        prompt = build_system_prompt("测试", "<p>正文</p>")

        self.assertIn("并行", prompt)
        self.assertIn("只读工具", prompt)

    def test_prompt_maps_attached_template_tokens_to_their_ordered_templates(self) -> None:
        prompt = build_system_prompt(
            "测试",
            "<p>正文</p>",
            attached_templates=[
                {"id": 7, "name": "排版尾", "html": "<section>尾部</section>"},
                {"id": 9, "name": "关注卡", "html": "<section>关注</section>"},
            ],
        )

        self.assertIn("@组件1：排版尾（ID 7）", prompt)
        self.assertIn("@组件2：关注卡（ID 9）", prompt)
        self.assertIn("必须在任何文档写入或最终回复前先调用 `read_attached_templates`", prompt)


if __name__ == "__main__":
    unittest.main()
