import unittest

from app.services.html_validation import validate_html_structure


class HtmlValidationTests(unittest.TestCase):
    def test_reports_missing_outer_closing_tag(self) -> None:
        report = validate_html_structure("<section><p>content</p>")

        self.assertFalse(report.valid)
        self.assertTrue(any("</section>" in error for error in report.errors))

    def test_reports_unmatched_closing_tag(self) -> None:
        report = validate_html_structure("<section>content</div>")

        self.assertFalse(report.valid)
        self.assertTrue(any("</div>" in error for error in report.errors))

    def test_accepts_complete_html_fragment(self) -> None:
        report = validate_html_structure("<section><p>content<br></p><img src=\"/image.png\"></section>")

        self.assertTrue(report.valid)
        self.assertEqual(report.errors, ())

    def test_reports_exact_opening_position_and_required_fix(self) -> None:
        report = validate_html_structure("<section>\n  <strong>content\n</section>")

        self.assertFalse(report.valid)
        issue = report.issues[0]
        self.assertEqual(issue.code, "missing_end_tag_before_close")
        self.assertEqual((issue.line, issue.column, issue.tag), (3, 1, "section"))
        self.assertIn("<strong>（始于第 2 行第 3 列）", issue.message)
        self.assertIn("请在 </section> 前补上 </strong>", issue.message)

    def test_accepts_raw_text_and_rcdata_without_parsing_example_tags(self) -> None:
        cases = (
            '<section><textarea><section data-example="true"></textarea></section>',
            "<section><title><section></title></section>",
            '<section><script>const marker = "<!-- <section>";</script></section>',
            '<section><style>.x::before { content: "<!-- <section>"; }</style></section>',
        )

        for html in cases:
            with self.subTest(html=html):
                self.assertTrue(validate_html_structure(html).valid)

    def test_accepts_html5_optional_end_tags(self) -> None:
        cases = (
            "<!doctype html><html><head><title>x</title></head><body><main>x</main>",
            "<p><ruby>汉<rt>han<rt>hàn</ruby></p>",
            "<table><tbody><tr><td>a<td>b</table>",
            "<ul><li>one<li>two</ul>",
        )

        for html in cases:
            with self.subTest(html=html):
                self.assertTrue(validate_html_structure(html).valid)

    def test_accepts_explicit_p_close_after_browser_implicitly_closes_it(self) -> None:
        report = validate_html_structure(
            '<section><p><section><img src="/image.png"></section></p><section>正文</section></section>'
        )

        self.assertTrue(report.valid)
        self.assertEqual(report.errors, ())
        self.assertEqual(len(report.warnings), 1)
        self.assertEqual(report.issues[0].code, "html5.unexpected-end-tag")
        self.assertEqual(report.issues[0].severity, "warning")
        self.assertIn("正文仍可安全加载", report.warnings[0])
        self.assertEqual(report.to_dict()["issues"][0]["severity"], "warning")

    def test_blocking_error_is_not_hidden_by_many_recoverable_warnings(self) -> None:
        html = "<p><section>正文</section></p>" * 12 + '<div class="'

        report = validate_html_structure(html)

        self.assertFalse(report.valid)
        self.assertEqual(report.issues[0].code, "html5.eof-in-attribute-value-double-quote")
        self.assertTrue(report.errors)

    def test_accepts_context_dependent_table_fragments(self) -> None:
        for html in ("<tr><td>x</td></tr>", "<td>x</td>", "<col>"):
            with self.subTest(html=html):
                self.assertTrue(validate_html_structure(html).valid)

    def test_reports_non_void_self_closing_tag(self) -> None:
        report = validate_html_structure("<section><div/>tail</section>")

        self.assertFalse(report.valid)
        issue = next(item for item in report.issues if item.code == "html5.non-void-element-with-trailing-solidus")
        self.assertEqual(issue.tag, "div")
        self.assertIn("<div></div>", issue.message)

    def test_accepts_foreign_content_self_closing_tag(self) -> None:
        report = validate_html_structure('<svg><path d="M0 0"/></svg>')

        self.assertTrue(report.valid)

    def test_reports_nested_anchor_that_browser_would_reparent(self) -> None:
        report = validate_html_structure('<section><a href="#1">one<a href="#2">two</a></a></section>')

        self.assertFalse(report.valid)
        issue = next(item for item in report.issues if item.code == "html5.unexpected-start-tag-implies-end-tag")
        self.assertEqual(issue.tag, "a")
        self.assertIn("提前闭合外层 <a>", issue.message)

    def test_reports_content_that_browser_would_move_out_of_table(self) -> None:
        report = validate_html_structure("<table><div>x</div><tr><td>y</td></tr></table>")

        self.assertFalse(report.valid)
        self.assertTrue(any("浏览器会把它移出表格" in error for error in report.errors))

    def test_reports_unclosed_comment_before_cascading_tag_errors(self) -> None:
        report = validate_html_structure("<section><!-- unfinished</section>")

        self.assertFalse(report.valid)
        self.assertEqual(report.issues[0].code, "html5.eof-in-comment")
        self.assertIn("补上 -->", report.issues[0].message)

    def test_reports_truncated_attribute_before_cascading_tag_errors(self) -> None:
        report = validate_html_structure('<section><div class="broken></div></section>')

        self.assertFalse(report.valid)
        self.assertEqual(report.issues[0].code, "html5.eof-in-attribute-value-double-quote")
        self.assertIn("成对的引号", report.issues[0].message)

    def test_returns_structured_issues_for_tool_consumers(self) -> None:
        payload = validate_html_structure("<section>broken").to_dict()

        self.assertFalse(payload["valid"])
        self.assertIn("第 1 行第 1 列", payload["errors"][0])
        self.assertEqual(payload["issues"][0]["code"], "missing_end_tag_at_eof")
        self.assertEqual(payload["issues"][0]["tag"], "section")

    def test_accepts_deep_explicit_nesting(self) -> None:
        html = "<section>" + "<div>" * 500 + "content" + "</div>" * 500 + "</section>"

        self.assertTrue(validate_html_structure(html).valid)


if __name__ == "__main__":
    unittest.main()
