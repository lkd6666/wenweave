import json
import unittest

from app.services.html_workspace import MAX_PATCH_OPERATIONS, HtmlWorkspace, WorkspaceError
from app.services.selected_elements import redact_inline_data, redact_inline_data_for_identity
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

        with self.assertRaisesRegex(WorkspaceError, "旧内容") as raised:
            workspace.apply_patch(
                workspace.revision,
                [{"block_id": block["block_id"], "expected_hash": "stale", "mode": "replace_inner", "html": "新内容"}],
                lambda value: value,
            )

        self.assertEqual(raised.exception.details["current_revision"], workspace.revision)
        self.assertEqual(raised.exception.details["current_hash"], block["expected_hash"])
        self.assertEqual(raised.exception.details["current_block"]["block_id"], block["block_id"])
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
        self.assertEqual(resolved.status, "exact")
        self.assertEqual(resolved.tag, "p")
        self.assertEqual(resolved.text, "目标段落")

    def test_selection_resolves_inline_node_to_its_editable_parent_block(self) -> None:
        workspace = self.make_workspace('<p>前缀<span data-anchor="target">目标</span>后缀</p>')
        resolved = workspace.resolve_selection(
            "p:nth-of-type(1) > span:nth-of-type(1)",
            "span",
            "目标",
            '<span data-anchor="target">目标</span>',
            {
                "path": "p:nth-of-type(1) > span:nth-of-type(1)",
                "parent_path": "p:nth-of-type(1)",
                "sibling_index": 1,
                "fingerprint": {
                    "tag_name": "span",
                    "stable_attributes": {"data-anchor": "target"},
                    "text": "目标",
                },
            },
        )

        self.assertEqual(resolved.status, "exact")
        self.assertEqual(resolved.tag, "span")
        self.assertEqual(resolved.path, "p:nth-of-type(1) > span:nth-of-type(1)")
        self.assertEqual(resolved.block.tag if resolved.block else "", "p")

    def test_selection_relocates_unique_image_by_stable_source(self) -> None:
        workspace = self.make_workspace(
            '<section><p>正文</p><div class="tail"><img src="https://cdn.example/target.png"></div></section>'
        )
        resolved = workspace.resolve_selection(
            "article:nth-of-type(1) > img:nth-of-type(1)",
            "img",
            "",
            '<img src="https://cdn.example/target.png">',
            {
                "path": "article:nth-of-type(1) > img:nth-of-type(1)",
                "parent_path": "article:nth-of-type(1)",
                "sibling_index": 1,
                "fingerprint": {
                    "tag_name": "img",
                    "stable_attributes": {"src": "https://cdn.example/target.png"},
                    "text": "",
                },
            },
        )

        self.assertEqual(resolved.status, "relocated")
        self.assertEqual(resolved.tag, "img")

    def test_selection_relocates_inline_image_by_redacted_identity(self) -> None:
        source = "data:image/png;base64,AAAA"
        workspace = self.make_workspace(f"<section><p>前言</p><p><img src=\"{source}\"></p></section>")
        resolved = workspace.resolve_selection(
            "section:nth-of-type(1) > p:nth-of-type(1) > img:nth-of-type(1)",
            "img",
            "",
            '<img src="[inline image data omitted]">',
            {
                "path": "section:nth-of-type(1) > p:nth-of-type(1) > img:nth-of-type(1)",
                "parent_path": "section:nth-of-type(1) > p:nth-of-type(1)",
                "sibling_index": 1,
                "fingerprint": {
                    "tag_name": "img",
                    "stable_attributes": {"src": redact_inline_data_for_identity(source)},
                    "text": "",
                },
            },
        )

        self.assertEqual(resolved.status, "relocated")
        self.assertEqual(resolved.path, "section:nth-of-type(1) > p:nth-of-type(2) > img:nth-of-type(1)")

    def test_selection_does_not_fallback_to_first_duplicate_image(self) -> None:
        workspace = self.make_workspace(
            '<p><img src="https://cdn.example/same.png"></p><p><img src="https://cdn.example/same.png"></p>'
        )
        resolved = workspace.resolve_selection(
            "section:nth-of-type(9) > img:nth-of-type(7)",
            "img",
            "",
            '<img src="https://cdn.example/same.png">',
            {
                "path": "section:nth-of-type(9) > img:nth-of-type(7)",
                "parent_path": "section:nth-of-type(9)",
                "sibling_index": 7,
                "fingerprint": {
                    "tag_name": "img",
                    "stable_attributes": {"src": "https://cdn.example/same.png"},
                    "text": "",
                },
            },
        )

        self.assertEqual(resolved.status, "ambiguous")
        self.assertEqual(resolved.block_id, "")

    def test_selection_reports_missing_when_identity_disappears(self) -> None:
        workspace = self.make_workspace('<p><img src="https://cdn.example/other.png"></p>')
        resolved = workspace.resolve_selection(
            "p:nth-of-type(1) > img:nth-of-type(1)",
            "img",
            "",
            '<img src="https://cdn.example/missing.png">',
            {
                "path": "p:nth-of-type(1) > img:nth-of-type(1)",
                "parent_path": "p:nth-of-type(1)",
                "sibling_index": 1,
                "fingerprint": {
                    "tag_name": "img",
                    "stable_attributes": {"src": "https://cdn.example/missing.png"},
                    "text": "",
                },
            },
        )

        self.assertEqual(resolved.status, "missing")
        self.assertEqual(resolved.block_id, "")

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

    def test_precomputed_paths_support_thousands_of_sibling_blocks(self) -> None:
        workspace = HtmlWorkspace("".join(f"<p>段落 {index}</p>" for index in range(2_000)))

        self.assertEqual(len(workspace.blocks), 2_000)
        self.assertEqual(workspace.blocks[-1].path, "p:nth-of-type(2000)")
        self.assertEqual(workspace.search("段落 1999")["results"][0]["path"], "p:nth-of-type(2000)")

    def test_search_pages_all_matching_blocks_without_duplicates(self) -> None:
        workspace = HtmlWorkspace("".join(f'<p class="match">候选 {index}</p>' for index in range(65)))

        cursor = 0
        seen: list[str] = []
        while True:
            page = workspace.search("match", limit=12, cursor=cursor)
            seen.extend(item["block_id"] for item in page["results"])
            if page["next_cursor"] is None:
                break
            self.assertGreater(page["next_cursor"], cursor)
            cursor = page["next_cursor"]

        self.assertEqual(len(seen), 65)
        self.assertEqual(len(set(seen)), 65)
        with self.assertRaisesRegex(WorkspaceError, "搜索游标超出范围"):
            workspace.search("match", cursor=65)

    def test_original_inline_data_changes_revision_and_never_leaks_from_attributes(self) -> None:
        source_a = '<p style="background:url(data:image/png;base64,STYLE-A)"><img src="data:image/png;base64,IMAGE-A">正文</p>'
        source_b = source_a.replace("STYLE-A", "STYLE-B").replace("IMAGE-A", "IMAGE-B")
        first = HtmlWorkspace(source_a, redact=redact_inline_data)
        second = HtmlWorkspace(source_b, redact=redact_inline_data)

        self.assertNotEqual(first.revision, second.revision)
        self.assertNotEqual(first.blocks[0].expected_hash, second.blocks[0].expected_hash)
        model_visible = json.dumps(first.map_payload(), ensure_ascii=False)
        self.assertNotIn("data:image", model_visible)
        self.assertNotIn("STYLE-A", model_visible)
        self.assertNotIn("IMAGE-A", model_visible)

    def test_batch_patch_accepts_sixty_four_blocks_and_rejects_more_atomically(self) -> None:
        source = "".join(f"<p>旧 {index}</p>" for index in range(MAX_PATCH_OPERATIONS))
        workspace = HtmlWorkspace(source)
        operations = [
            {
                "block_id": block.block_id,
                "expected_hash": block.expected_hash,
                "mode": "replace_inner",
                "html": f"新 {index}",
            }
            for index, block in enumerate(workspace.blocks)
        ]

        updated, summary = workspace.apply_patch(workspace.revision, operations, lambda value: value)

        self.assertEqual(summary["operation_count"], MAX_PATCH_OPERATIONS)
        self.assertEqual(updated.count("新 "), MAX_PATCH_OPERATIONS)

        oversized_source = "".join(f"<p>旧 {index}</p>" for index in range(MAX_PATCH_OPERATIONS + 1))
        oversized = HtmlWorkspace(oversized_source)
        oversized_operations = [
            {
                "block_id": block.block_id,
                "expected_hash": block.expected_hash,
                "mode": "replace_inner",
                "html": "新",
            }
            for block in oversized.blocks
        ]
        with self.assertRaisesRegex(WorkspaceError, "一次最多执行 64"):
            oversized.apply_patch(oversized.revision, oversized_operations, lambda value: value)
        self.assertEqual(oversized.source_html, oversized_source)

    def test_image_inventory_locates_article_images_by_current_semantic_context(self) -> None:
        workspace = self.make_workspace(
            "<article>"
            "<p>福工大电气团演讲比赛通知</p><p><img src='https://cdn.example/logo.png'></p>"
            "<p>主标题后的宣传横幅</p><p><img src='https://cdn.example/banner.png' alt='演讲比赛横幅'></p>"
            "<p>一、活动主题</p><p><img src='https://cdn.example/theme.png'></p>"
            "<p>二、活动对象</p><p><img src='https://cdn.example/audience.png'></p>"
            "<p>七、报名方式</p><p><img src='https://cdn.example/signup.png'></p>"
            "<p>附件 1：</p><p><img src='https://cdn.example/form.png'></p>"
            "<p>附件 2：</p><p><img src='https://cdn.example/qrcode.png'></p>"
            "</article>"
        )

        title = workspace.image_inventory(query="宣传横幅", limit=8)
        theme = workspace.image_inventory(query="活动主题", limit=8)
        signup = workspace.image_inventory(query="报名方式", limit=8)

        self.assertEqual(title["match_count"], 1)
        self.assertEqual(theme["match_count"], 1)
        self.assertEqual(signup["match_count"], 1)
        self.assertEqual([item["slot"] for item in title["images"]], [2])
        self.assertEqual([item["slot"] for item in theme["images"]], [3])
        self.assertEqual([item["slot"] for item in signup["images"]], [5])
        self.assertIn("前文：一、活动主题", theme["images"][0]["location_label"])
        self.assertEqual(theme["images"][0]["section"], "一、活动主题")
        self.assertTrue(theme["images"][0]["match_reasons"])

    def test_image_inventory_exposes_semantic_metadata_but_not_image_sources(self) -> None:
        secret_url = "https://private.example/assets/should-not-leak.png?token=secret"
        secret_srcset = "https://private.example/assets/should-not-leak-2x.png 2x"
        inline = "data:image/png;base64,TOP-SECRET"
        workspace = HtmlWorkspace(
            "<section><h2>图片章节</h2><figure>"
            f"<img src='{secret_url}' srcset='{secret_srcset}' alt='校园活动海报' title='宣传图' aria-label='活动视觉'>"
            "<figcaption>图 1：活动现场</figcaption></figure>"
            f"<p><img src='{inline}' alt='二维码'></p></section>",
            redact=redact_inline_data,
        )

        payload = workspace.image_inventory(query="活动现场", limit=8)
        rendered = json.dumps(payload, ensure_ascii=False)
        first = payload["images"][0]

        self.assertEqual(payload["match_count"], 1)
        self.assertEqual(first["alt"], "校园活动海报")
        self.assertEqual(first["caption"], "图 1：活动现场")
        self.assertEqual(first["aria_label"], "活动视觉")
        self.assertNotIn(secret_url, rendered)
        self.assertNotIn(secret_srcset, rendered)
        self.assertNotIn(inline, rendered)
        self.assertNotIn("TOP-SECRET", rendered)

    def test_image_inventory_paginates_and_reports_ambiguous_candidates(self) -> None:
        workspace = self.make_workspace(
            "".join(
                f"<section><p>校园报名方式 {index}</p><figure>"
                f"<img src='https://cdn.example/{index}.png' alt='报名图'><figcaption>报名说明 {index}</figcaption>"
                "</figure></section>"
                for index in range(3)
            )
        )

        first_page = workspace.image_inventory(query="报名方式", limit=2)
        second_page = workspace.image_inventory(query="报名方式", limit=2, cursor=first_page["next_cursor"])

        self.assertEqual(first_page["match_count"], 3)
        self.assertEqual(len(first_page["images"]), 2)
        self.assertEqual(first_page["next_cursor"], 2)
        self.assertEqual(len(second_page["images"]), 1)
        self.assertIsNone(second_page["next_cursor"])
        self.assertEqual(first_page["images"][0]["match_reasons"], ["前文"])

    def test_search_indexes_safe_image_text_attributes_without_indexing_sources(self) -> None:
        source_url = "https://cdn.example/private-image.png"
        workspace = self.make_workspace(
            f"<p><img src='{source_url}' srcset='https://cdn.example/private-2x.png 2x' "
            "alt='民族团结主题插画' title='活动插图' aria-label='主题配图'></p>"
        )

        result = workspace.search("民族团结主题插画")
        rendered = json.dumps(workspace.map_payload(), ensure_ascii=False)

        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["results"][0]["tag"], "img")
        self.assertIn('alt="民族团结主题插画"', result["results"][0]["attributes"])
        self.assertNotIn(source_url, rendered)
        self.assertNotIn("private-2x", rendered)


if __name__ == "__main__":
    unittest.main()
