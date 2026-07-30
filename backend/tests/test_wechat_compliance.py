import unittest

from app.services.wechat_compliance import NEST_LIMIT, SVG_LENGTH_LIMIT, run_compliance_check


class WechatComplianceTests(unittest.TestCase):
    def test_reports_previously_unreported_markup_css_svg_and_image_rules(self) -> None:
        html = """
        <style>.card { color: red; }</style>
        <link rel="stylesheet" href="https://example.test/article.css">
        <script>window.alert('unsupported')</script>
        <iframe src="https://example.test/embed"></iframe>
        <noscript>fallback</noscript>
        <section id="test-zone" class="custom-compliance-test"
          style="position:absolute; z-index:2; top:0; left:0; display:grid;
                 grid-template-columns:1fr 1fr; transform:translateX(1px)">
          <img src="https://example.test/image.png" width="640">
          <br><br><br><br><br><br><br><br><br><br>
          <svg id="diagram"><g id="trigger"><rect></rect><animate begin="trigger.click"></animate><br></g></svg>
        </section>
        """

        report = run_compliance_check(html).to_dict()
        codes = {item["code"] for item in report["diagnostics"]}

        self.assertTrue(report["hasError"])
        self.assertTrue(report["hasWarning"])
        self.assertEqual(report["bannedTags"], ["style", "link", "script", "iframe", "noscript"])
        self.assertEqual(report["consecutiveBrRuns"], [10])
        self.assertEqual(report["removedSvgBrs"], 1)
        self.assertTrue(report["hasSvg"])
        self.assertIn('<svg id="diagram">', report["svgIdAttributes"])
        self.assertIn('<g id="trigger">', report["svgIdAttributes"])
        self.assertIn("custom-compliance-test", report["removedClasses"])
        self.assertIn('<section id="test-zone">', report["removedIdAttributes"])
        self.assertIn("position", report["riskStyleHints"][0])
        self.assertTrue(report["imageIssues"])
        self.assertNotIn("<rect></rect>", report["emptyNodeSuspects"])

        for code in {
            "WX-TAG-001", "WX-TAG-002", "WX-TAG-003", "WX-TAG-004", "WX-TAG-005",
            "WX-CSS-001", "WX-CSS-002", "WX-CSS-003", "WX-CSS-004",
            "WX-HTML-001", "WX-SVG-001", "WX-SVG-002", "WX-IMG-001", "WX-IMG-002", "WX-IMG-003",
        }:
            self.assertIn(code, codes)

        for diagnostic in report["diagnostics"]:
            self.assertTrue(diagnostic["path"])
            self.assertIn("message", diagnostic)
            self.assertIn("consequence", diagnostic)
            self.assertIn("suggestion", diagnostic)

    def test_enforces_svg_hard_limit_and_nesting_limit(self) -> None:
        svg = "<svg>" + ("x" * (SVG_LENGTH_LIMIT - len("<svg></svg>"))) + "</svg>"
        nested = "<section>" * NEST_LIMIT + svg + "</section>" * NEST_LIMIT

        report = run_compliance_check(nested).to_dict()
        codes = {item["code"] for item in report["diagnostics"]}

        self.assertEqual(report["oversizedSvgBlocks"], [SVG_LENGTH_LIMIT])
        self.assertEqual(report["maxNestingDepth"], NEST_LIMIT)
        self.assertTrue(report["willFlattenNesting"])
        self.assertTrue(report["hasError"])
        self.assertIn("WX-SVG-003", codes)
        self.assertIn("WX-HTML-002", codes)

    def test_allows_nesting_below_word_paste_threshold(self) -> None:
        nested = "<section>" * (NEST_LIMIT - 1) + "内容" + "</section>" * (NEST_LIMIT - 1)

        report = run_compliance_check(nested).to_dict()

        self.assertEqual(report["maxNestingDepth"], NEST_LIMIT - 1)
        self.assertFalse(report["willFlattenNesting"])
        self.assertNotIn("WX-HTML-002", {item["code"] for item in report["diagnostics"]})

    def test_svg_graphic_elements_are_not_reported_as_empty_nodes(self) -> None:
        report = run_compliance_check("<svg><rect></rect><circle></circle><path></path></svg>").to_dict()

        self.assertEqual(report["emptyNodeSuspects"], [])
        self.assertFalse(report["hasError"])
        self.assertFalse(report["hasWarning"])

    def test_accepts_responsive_image_with_alt_text(self) -> None:
        report = run_compliance_check(
            '<img src="https://example.test/image.png" alt="Example" '
            'style="max-width:100%; height:auto; display:block; width:100%">'
        ).to_dict()

        self.assertEqual(report["imageIssues"], [])
        self.assertFalse(report["hasWarning"])


if __name__ == "__main__":
    unittest.main()
