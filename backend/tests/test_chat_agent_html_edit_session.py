import unittest

from app.services.chat_agent import (
    EDIT_COMPLETION_CONFIRMATION,
    HtmlEditSession,
    _short,
    _require_edit_completion,
)


class HtmlEditSessionSafetyTests(unittest.TestCase):
    def test_tool_activity_summary_shortener_is_available(self) -> None:
        self.assertEqual(_short("  查找\n排版块  ", 20), "查找 排版块")
        self.assertEqual(_short("abcdef", 4), "abc…")

    def test_long_document_can_be_overwritten_in_full(self) -> None:
        source = "<section>" + ("x" * 20_000) + "</section>"
        session = HtmlEditSession(source)

        result, _ = session.replace_full("<section>new content</section>")

        self.assertIn("已整体替换", result)
        self.assertEqual(session.html, "<section>new content</section>")
        self.assertTrue(session.edited)

    def test_small_document_can_be_replaced_in_full(self) -> None:
        session = HtmlEditSession("")

        result, _ = session.replace_full("<section><p>new content</p></section>")

        self.assertIn("已整体替换", result)
        self.assertEqual(session.html, "<section><p>new content</p></section>")
        self.assertTrue(session.edited)

    def test_large_patch_can_replace_a_unique_section(self) -> None:
        source = "<p>old</p>"
        session = HtmlEditSession(source)
        replacement = "<section>" + ("x" * 20_000) + "</section>"

        result, _ = session.str_replace(source, replacement)

        self.assertIn("替换成功", result)
        self.assertEqual(session.html, replacement)
        self.assertTrue(session.edited)

    def test_batch_replace_applies_multiple_rules_in_order(self) -> None:
        session = HtmlEditSession("<p>first</p><p>second</p>")

        result, _ = session.batch_replace(
            [
                {"old_str": "<p>first</p>", "new_str": "<p>one</p>"},
                {"old_str": "<p>second</p>", "new_str": "<p>two</p>"},
            ]
        )

        self.assertIn("批量替换成功（2 条规则，共 2 处", result)
        self.assertEqual(session.html, "<p>one</p><p>two</p>")

    def test_batch_replace_is_atomic_when_a_rule_fails(self) -> None:
        source = "<p>first</p><p>second</p>"
        session = HtmlEditSession(source)

        with self.assertRaisesRegex(ValueError, "第 2 条替换未找到"):
            session.batch_replace(
                [
                    {"old_str": "<p>first</p>", "new_str": "<p>one</p>"},
                    {"old_str": "<p>missing</p>", "new_str": "<p>two</p>"},
                ]
            )

        self.assertEqual(session.html, source)
        self.assertFalse(session.edited)

    def test_batch_replace_can_explicitly_replace_all_matching_sections(self) -> None:
        session = HtmlEditSession("<p>same</p><p>same</p><p>same</p>")

        result, _ = session.batch_replace(
            [{"old_str": "<p>same</p>", "new_str": "<p>updated</p>", "replace_all": True}]
        )

        self.assertIn("共 3 处", result)
        self.assertEqual(session.html, "<p>updated</p><p>updated</p><p>updated</p>")

    def test_missing_completion_confirmation_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "未完成确认"):
            _require_edit_completion("", "整体替换")

        _require_edit_completion(EDIT_COMPLETION_CONFIRMATION, "整体替换")


if __name__ == "__main__":
    unittest.main()
