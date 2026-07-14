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


if __name__ == "__main__":
    unittest.main()
