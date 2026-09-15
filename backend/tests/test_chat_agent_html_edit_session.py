import unittest

from app.services.chat_agent import (
    HtmlEditSession,
    _parse_attached_template_ids,
    _parse_gzh_theme_component_ids,
    _short,
    build_system_prompt,
    validate_gzh_theme_candidate,
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

    def test_theme_component_reader_parses_json_array_string(self) -> None:
        parsed = _parse_gzh_theme_component_ids('["1", "2", "6d"]')

        self.assertEqual(parsed, ["1", "2", "6d"])

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

    def test_full_replacement_invalidates_run_local_block_ids(self) -> None:
        session = HtmlEditSession("<p>old content</p>")
        old = next(item for item in session.search("old content")["results"] if item["tag"] == "p")

        summary = session.replace_document(
            session.document_map()["revision"],
            "<p>old content</p><p>new content</p>",
        )

        self.assertTrue(summary["continuity"]["full_replacement"])
        with self.assertRaisesRegex(WorkspaceError, "search_html"):
            session.read_blocks([old["block_id"]])

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

    def test_workspace_index_is_reused_until_a_successful_write(self) -> None:
        session = HtmlEditSession("<p>first</p><p>second</p>")
        initial = session.workspace()
        first_id = initial.search("first")["results"][0]["block_id"]

        session.document_map()
        session.search("second")
        session.read_blocks([first_id])
        session.set_effective_tool_result_limit(512)
        session.document_map()

        before_write = session.workspace_metrics()
        self.assertEqual(before_write["index_builds"], 1)
        self.assertGreaterEqual(before_write["cache_hits"], 4)
        self.assertIs(session.workspace(), initial)

        session.patch_blocks(
            initial.revision,
            _patch_operations(session, ("first", "updated")),
        )

        # The accepted write eagerly builds the next run-local index so the
        # continuity summary and the following model turn share one cache.
        self.assertEqual(session.workspace_metrics()["index_builds"], 2)
        self.assertEqual(session.workspace_metrics()["cache_invalidations"], 1)
        next_workspace = session.workspace()
        self.assertIsNot(next_workspace, initial)
        self.assertEqual(session.workspace_metrics()["index_builds"], 2)

    def test_untouched_blocks_keep_identity_and_can_be_patched_without_reading_again(self) -> None:
        session = HtmlEditSession("<section><p>first</p><p>second</p><p>third</p></section>")
        first = next(item for item in session.search("first")["results"] if item["tag"] == "p")
        second = next(item for item in session.search("second")["results"] if item["tag"] == "p")
        second_hash = session.read_blocks([second["block_id"]])["blocks"][0]["expected_hash"]

        summary = session.patch_blocks(
            session.document_map()["revision"],
            [{
                "block_id": first["block_id"],
                "expected_hash": first["expected_hash"],
                "mode": "replace_inner",
                "html": "FIRST-UPDATED",
            }],
        )

        self.assertEqual(summary["continuity"]["preserved_block_count"], 2)
        self.assertEqual(
            session.read_blocks([second["block_id"]])["blocks"][0]["text"],
            "second",
        )
        second_summary = session.patch_blocks(
            summary["revision"],
            [{
                "block_id": second["block_id"],
                "expected_hash": second_hash,
                "mode": "replace_inner",
                "html": "SECOND-UPDATED",
            }],
        )
        self.assertIn("SECOND-UPDATED", session.html)
        self.assertEqual(second_summary["continuity"]["preserved_block_count"], 2)

    def test_shifted_blocks_keep_identity_after_insert_before(self) -> None:
        session = HtmlEditSession("<section><p>first</p><p>tail</p></section>")
        first = next(item for item in session.search("first")["results"] if item["tag"] == "p")
        tail = next(item for item in session.search("tail")["results"] if item["tag"] == "p")

        summary = session.patch_blocks(
            session.document_map()["revision"],
            [{
                "block_id": first["block_id"],
                "expected_hash": first["expected_hash"],
                "mode": "insert_before",
                "html": "<p>inserted</p>",
            }],
        )

        self.assertEqual(summary["continuity"]["preserved_block_count"], 2)
        self.assertEqual(session.read_blocks([tail["block_id"]])["blocks"][0]["text"], "tail")

    def test_unique_block_relocates_when_its_ancestor_is_replaced(self) -> None:
        session = HtmlEditSession("<section><p>keep me</p></section>")
        section = next(item for item in session.document_map()["blocks"] if item["tag"] == "section")
        paragraph = next(item for item in session.search("keep me")["results"] if item["tag"] == "p")

        summary = session.patch_blocks(
            session.document_map()["revision"],
            [{
                "block_id": section["block_id"],
                "expected_hash": section["expected_hash"],
                "mode": "replace_outer",
                "html": "<article><p>keep me</p></article>",
            }],
        )

        self.assertEqual(summary["continuity"]["relocated_block_count"], 1)
        self.assertEqual(session.read_blocks([paragraph["block_id"]])["blocks"][0]["text"], "keep me")

    def test_duplicate_candidates_are_not_auto_relocated(self) -> None:
        session = HtmlEditSession("<section><p>same</p><p>same</p></section>")
        paragraphs = [item for item in session.search("same")["results"] if item["tag"] == "p"]
        section = next(item for item in session.document_map()["blocks"] if item["tag"] == "section")

        summary = session.patch_blocks(
            session.document_map()["revision"],
            [{
                "block_id": section["block_id"],
                "expected_hash": section["expected_hash"],
                "mode": "replace_outer",
                "html": "<article><p>same</p><p>same</p></article>",
            }],
        )

        self.assertEqual(summary["continuity"]["relocated_block_count"], 0)
        with self.assertRaisesRegex(WorkspaceError, "search_html") as raised:
            session.read_blocks([paragraphs[0]["block_id"]])
        self.assertEqual(raised.exception.details["reason"], "block_id_not_current")
        self.assertEqual(raised.exception.details["suggested_query"], "same")

    def test_invalid_patch_is_written_and_checkpointed_with_warning_diagnostics(self) -> None:
        checkpoints: list[str] = []
        session = HtmlEditSession("<p>old</p>", checkpoint_callback=checkpoints.append)
        operation = _patch_operations(session, ("old", "<strong>broken"))[0]

        session.patch_blocks(session.document_map()["revision"], [operation])

        self.assertEqual(session.html, "<p><strong>broken</p>")
        self.assertTrue(session.edited)
        self.assertFalse(session.validate_html().valid)
        session.persist_checkpoint()
        self.assertEqual(checkpoints, [session.html])

    def test_invalid_full_replacement_is_written_and_checkpointed_with_warning_diagnostics(self) -> None:
        checkpoints: list[str] = []
        session = HtmlEditSession("<p>old</p>", checkpoint_callback=checkpoints.append)

        session.replace_document(session.document_map()["revision"], "<section><strong>broken</section>")

        self.assertEqual(session.html, "<section><strong>broken</section>")
        self.assertTrue(session.edited)
        self.assertFalse(session.validate_html().valid)
        session.persist_checkpoint()
        self.assertEqual(checkpoints, [session.html])

    def test_warning_candidate_can_be_repaired_with_current_revision_and_local_patch(self) -> None:
        session = HtmlEditSession("<p>old</p>")
        session.replace_document(session.document_map()["revision"], "<section><strong>broken</section>")

        section = session.document_map()["blocks"][0]
        summary = session.patch_blocks(
            session.document_map()["revision"],
            [{
                "block_id": section["block_id"],
                "expected_hash": section["expected_hash"],
                "mode": "replace_inner",
                "html": "<strong>fixed</strong>",
            }],
        )

        self.assertTrue(session.validate_html().valid)
        self.assertEqual(session.html, "<section><strong>fixed</strong></section>")
        self.assertTrue(summary["revision"])

    def test_strict_theme_candidate_is_rejected_before_document_mutation(self) -> None:
        source = '<section><p><span leaf="">原文</span></p></section>'
        session = HtmlEditSession(source, candidate_validator=validate_gzh_theme_candidate)

        with self.assertRaisesRegex(WorkspaceError, "主题严格校验未通过") as raised:
            session.replace_document(
                session.document_map()["revision"],
                '<section style="float:left"><p>新正文</p></section>',
            )

        strict = raised.exception.details["gzh_validation"]
        self.assertTrue(strict["hasError"])
        self.assertGreaterEqual(len(strict["errors"]), 2)
        self.assertEqual(session.html, source)
        self.assertFalse(session.edited)

    def test_strict_theme_candidate_rejects_float_tag(self) -> None:
        source = '<section><p><span leaf="">原文</span></p></section>'
        session = HtmlEditSession(source, candidate_validator=validate_gzh_theme_candidate)

        with self.assertRaisesRegex(WorkspaceError, "<float>") as raised:
            session.replace_document(
                session.document_map()["revision"],
                '<section><float><span leaf="">正文</span></float></section>',
            )

        self.assertIn("<float>", " ".join(raised.exception.details["gzh_validation"]["errors"]))
        self.assertEqual(session.html, source)
        self.assertFalse(session.edited)

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
        self.assertIn("最多 64", prompt)
        self.assertIn("next_cursor", prompt)
        self.assertIn("模型可自行判断", prompt)
        self.assertIn("局部补丁会显著增加风险或复杂度", prompt)
        self.assertIn("同一次 Agent run 内", prompt)
        self.assertIn("不要为单个局部目标重新读取整张地图", prompt)

    def test_prompt_uses_current_semantic_image_locator_for_model_decided_replacements(self) -> None:
        prompt = build_system_prompt("测试", "<p><img src='https://cdn.example/image.png'></p>")

        self.assertIn("涉及现有图片时先调用 `inspect_current_images`", prompt)
        self.assertIn("不得用历史图片 URL、历史 block_id 或臆测的 alt", prompt)
        self.assertIn("同一目标下的一批配图替换是单步操作", prompt)
        self.assertIn("模型根据任务目标自行判断是否需要编辑或替换", prompt)

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
