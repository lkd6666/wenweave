from __future__ import annotations

import json
import unittest

from langchain_core.tools import tool
from pydantic import BaseModel

from app.services.tool_call_recovery import prepare_tool_arguments


@tool
def search(query: str, limit: int = 8, cursor: int | str = 0) -> str:
    """Search a document."""
    return query


@tool
def read_blocks(block_ids: list[str], cursor: int = 0) -> str:
    """Read exact blocks."""
    return str(block_ids)


@tool
def apply_html_patch(revision: str, operations: list[dict]) -> str:
    """Patch a document."""
    return revision


class Reference(BaseModel):
    kind: str
    image_slot: int = 0


@tool
def view_images(references: list[Reference], include_image: bool = True) -> str:
    """View references."""
    return str(references)


class ToolCallRecoveryTests(unittest.TestCase):
    def test_unwraps_encoded_parameters_and_preserves_original_input(self) -> None:
        arguments = {"parameters": json.dumps({"keyword": "旧标题", "limit": None, "cursor": "0"})}
        original = dict(arguments)

        prepared, error = prepare_tool_arguments("search_html", arguments, search)

        self.assertIsNone(error)
        self.assertEqual(prepared, {"query": "旧标题", "cursor": "0"})
        self.assertEqual(arguments, original)

    def test_accepts_json_object_encoded_twice(self) -> None:
        arguments = json.dumps(json.dumps({"query": "标题"}))
        prepared, error = prepare_tool_arguments("search_html", arguments, search)
        self.assertIsNone(error)
        self.assertEqual(prepared, {"query": "标题"})

    def test_reads_single_id_and_json_array_without_splitting_identifiers(self) -> None:
        for arguments in ({"block_id": "b,1"}, {"block_ids": "b,1"}, {"block_ids": '["b,1"]'}):
            with self.subTest(arguments=arguments):
                prepared, error = prepare_tool_arguments("read_blocks", arguments, read_blocks)
                self.assertIsNone(error)
                self.assertEqual(prepared, {"block_ids": ["b,1"]})

    def test_incomplete_id_array_is_rejected(self) -> None:
        _, error = prepare_tool_arguments("read_blocks", {"block_ids": '["b1"'}, read_blocks)
        self.assertIsNotNone(error)
        self.assertEqual(error["field_errors"][0]["field"], "block_ids")

    def test_decodes_nested_containers_but_preserves_html_and_revision(self) -> None:
        html = '<p data-json=\'{"a":1}\'>原文  </p>'
        operations = [{"block_id": "b1", "expected_hash": "hash", "html": html}]
        prepared, error = prepare_tool_arguments(
            "apply_html_patch", {"revision": " revision ", "operations": json.dumps(operations)}, apply_html_patch
        )
        self.assertIsNone(error)
        self.assertEqual(prepared, {"revision": " revision ", "operations": operations})

    def test_resolves_nested_models_and_uses_default_for_optional_null(self) -> None:
        prepared, error = prepare_tool_arguments(
            "view_images", {"references": ['{"kind":"article","image_slot":null}'], "include_image": None}, view_images
        )
        self.assertIsNone(error)
        self.assertEqual(prepared, {"references": [{"kind": "article"}]})

    def test_missing_arguments_produce_precise_guidance_without_guessing(self) -> None:
        prepared, error = prepare_tool_arguments("search_html", {}, search)
        self.assertEqual(prepared, {})
        self.assertEqual(error["missing_fields"], ["query"])
        self.assertEqual(error["code"], "invalid_tool_arguments")
        self.assertEqual(error["example_arguments"], {"query": "目标正文关键词"})
        self.assertIn("不要传空对象", error["next_step"])
        self.assertNotIn("ToolInvocationError", error["error"])

    def test_missing_revision_is_not_filled_in(self) -> None:
        prepared, error = prepare_tool_arguments("apply_html_patch", {"operations": []}, apply_html_patch)
        self.assertNotIn("revision", prepared)
        self.assertEqual(error["missing_fields"], ["revision"])
        self.assertIn("不能补造版本号", error["next_step"])

    def test_required_null_and_whitespace_query_are_rejected(self) -> None:
        for query in (None, "", "  \n "):
            with self.subTest(query=query):
                _, error = prepare_tool_arguments("search_html", {"query": query}, search)
                self.assertIsNotNone(error)

    def test_truncated_json_is_not_repaired_or_echoed(self) -> None:
        prepared, error = prepare_tool_arguments("apply_html_patch", '{"revision":"r1","operations":[{"html":"secret', apply_html_patch)
        self.assertEqual(prepared, {})
        self.assertIn("完整", error["error"])
        self.assertNotIn("secret", json.dumps(error))

    def test_conflicting_aliases_do_not_choose_a_search_target(self) -> None:
        _, error = prepare_tool_arguments("search_html", {"keyword": "标题", "search_term": "正文"}, search)
        self.assertEqual(error["missing_fields"], ["query"])


if __name__ == "__main__":
    unittest.main()
