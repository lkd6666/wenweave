import json
import unittest

from app.services.html_workspace import HtmlWorkspace, WorkspaceError
from app.services.token_budget import estimate_tokens


class HtmlWorkspaceTests(unittest.TestCase):
    def make_workspace(self, source: str) -> HtmlWorkspace:
        return HtmlWorkspace(
            source,
            redact=lambda value: value.replace("data:image/png;base64,AAAA", "__YIBAN_INLINE_DATA_1__"),
        )

    def test_search_prefers_exact_leaf_block_in_minified_html(self) -> None:
        workspace = self.make_workspace(
            '<section class="article"><h1>标题</h1><p>开场文字</p><p class="target">需要修改的第二段</p></section>'
        )

        result = workspace.search("需要修改的第二段")

        self.assertEqual(result["results"][0]["tag"], "p")
        self.assertIn("target", result["results"][0]["attributes"])
        self.assertEqual(result["results"][0]["start_line"], 1)

    def test_read_and_patch_keep_inline_image_out_of_model_view_and_restore_it(self) -> None:
        source = '<p class="target">旧文案<img src="data:image/png;base64,AAAA"></p>'
        workspace = self.make_workspace(source)
        block = workspace.search("旧文案")["results"][0]

        read = workspace.read([block["block_id"]])
        self.assertIn("__YIBAN_INLINE_DATA_1__", read["blocks"][0]["html"])
        self.assertNotIn("data:image", read["blocks"][0]["html"])

        updated, summary = workspace.apply_patch(
            workspace.revision,
            [
                {
                    "block_id": block["block_id"],
                    "expected_hash": block["expected_hash"],
                    "mode": "replace_inner",
                    "html": '新文案<img src="__YIBAN_INLINE_DATA_1__">',
                }
            ],
            lambda value: value.replace("__YIBAN_INLINE_DATA_1__", "data:image/png;base64,AAAA"),
        )

        self.assertEqual(updated, '<p class="target">新文案<img src="data:image/png;base64,AAAA"></p>')
        self.assertEqual(summary["operation_count"], 1)

    def test_patch_rejects_stale_hash_without_mutating_source(self) -> None:
        source = "<p>第一段</p><p>第二段</p>"
        workspace = self.make_workspace(source)
        block = workspace.search("第一段")["results"][0]

        with self.assertRaisesRegex(WorkspaceError, "旧内容"):
            workspace.apply_patch(
                workspace.revision,
                [{"block_id": block["block_id"], "expected_hash": "stale", "mode": "replace_inner", "html": "新内容"}],
                lambda value: value,
            )

        self.assertEqual(workspace.source_html, source)

    def test_batch_patch_rejects_nested_blocks_atomically(self) -> None:
        source = "<section><p>正文</p></section>"
        workspace = self.make_workspace(source)
        section = next(block for block in workspace.blocks if block.tag == "section")
        paragraph = next(block for block in workspace.blocks if block.tag == "p")

        with self.assertRaisesRegex(WorkspaceError, "嵌套或重叠"):
            workspace.apply_patch(
                workspace.revision,
                [
                    {"block_id": section.block_id, "expected_hash": section.expected_hash, "mode": "replace_inner", "html": "x"},
                    {"block_id": paragraph.block_id, "expected_hash": paragraph.expected_hash, "mode": "replace_inner", "html": "y"},
                ],
                lambda value: value,
            )

        self.assertEqual(workspace.source_html, source)

    def test_selection_resolves_preview_selector_to_current_block(self) -> None:
        workspace = self.make_workspace("<section><p>前言</p><p>目标段落</p></section>")
        resolved = workspace.resolve_selection("section:nth-of-type(1) > p:nth-of-type(2)", "p", "目标段落")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.tag, "p")
        self.assertEqual(resolved.text, "目标段落")

    def test_read_rejects_oversized_html_without_returning_partial_markup(self) -> None:
        source = "<section><p>" + ("很长的正文" * 600) + "</p></section>"
        workspace = HtmlWorkspace(source, tool_result_max_tokens=180)
        block = next(block for block in workspace.blocks if block.tag == "section")

        with self.assertRaisesRegex(WorkspaceError, "未返回不完整 HTML"):
            workspace.read([block.block_id])

    def test_read_accepts_fourteen_requested_blocks(self) -> None:
        workspace = self.make_workspace("".join(f"<p>段落 {index}</p>" for index in range(14)))
        block_ids = [block.block_id for block in workspace.blocks[:14]]

        result = workspace.read(block_ids)

        self.assertEqual(len(result["blocks"]), 14)
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(result["remaining_block_count"], 0)

    def test_read_paginates_at_complete_block_boundaries(self) -> None:
        source = "".join(f"<p>段落 {index} " + (f"token-{index} " * 24) + "</p>" for index in range(12))
        workspace = HtmlWorkspace(source, tool_result_max_tokens=450)
        block_ids = [block.block_id for block in workspace.blocks[:12]]

        pages: list[dict] = []
        cursor = 0
        while True:
            page = workspace.read(block_ids, cursor)
            pages.append(page)
            if page["next_cursor"] is None:
                break
            cursor = page["next_cursor"]

        self.assertGreater(len(pages), 1)
        self.assertTrue(all(page["blocks"] for page in pages))
        self.assertEqual(
            [item["block_id"] for page in pages for item in page["blocks"]],
            block_ids,
        )

    def test_read_limit_reports_the_actual_requested_block_count(self) -> None:
        workspace = self.make_workspace("".join(f"<p>段落 {index}</p>" for index in range(17)))
        block_ids = [block.block_id for block in workspace.blocks[:17]]

        with self.assertRaisesRegex(WorkspaceError, "一次最多读取") as raised:
            workspace.read(block_ids)

        self.assertEqual(raised.exception.details["requested_block_count"], 17)
        self.assertEqual(raised.exception.details["max_read_blocks"], 16)

    def test_map_truncates_at_block_boundaries_within_configured_token_limit(self) -> None:
        source = "".join(f"<p class='item-{index}'>段落 {index} " + ("正文" * 80) + "</p>" for index in range(12))
        workspace = HtmlWorkspace(source, tool_result_max_tokens=420)

        result = workspace.map_payload()

        self.assertTrue(result.get("truncated"))
        self.assertLessEqual(estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(",", ":"))), 420)


if __name__ == "__main__":
    unittest.main()
