import asyncio
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.schemas.compliance import ComplianceReportRead
from app.services.wechat_compliance import (
    OFFICIAL_ENGINE_COMMIT,
    OFFICIAL_ENGINE_VERSION,
    OfficialComplianceEngine,
    _new_browser_event_loop,
    _parse_result,
)
from app.services.chat_agent import _read_wechat_compliance_spec_page


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "wechat_official"
RULE_PROMPT_PATH = Path(__file__).parents[2] / "rule.prompt.md"


class WechatComplianceTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows event-loop regression")
    def test_browser_worker_uses_proactor_even_under_selector_policy(self) -> None:
        original_policy = asyncio.get_event_loop_policy()
        loop = None
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            loop = _new_browser_event_loop()
            self.assertIsInstance(loop, asyncio.ProactorEventLoop)
        finally:
            if loop is not None:
                loop.close()
            asyncio.set_event_loop_policy(original_policy)

    def test_official_detail_spec_is_sectioned_and_pageable_for_the_model(self) -> None:
        first_page = _read_wechat_compliance_spec_page("darkmode")

        self.assertEqual(first_page["section"], "darkmode")
        self.assertIn("## 4、Dark Mode", first_page["content"])
        self.assertIsNotNone(first_page["next_cursor"])
        self.assertFalse(first_page["complete"])

        # The exemption sections are intentionally near the end of the
        # official Dark Mode chapter.  Reassemble all pages so the test
        # verifies the model can reach every detail rather than assuming a
        # specific page boundary.
        pages = [first_page]
        page = first_page
        while page["next_cursor"] is not None:
            page = _read_wechat_compliance_spec_page("darkmode", int(page["next_cursor"]))
            pages.append(page)
        content = "".join(str(item["content"]) for item in pages)

        self.assertGreater(len(pages), 1)
        self.assertTrue(pages[-1]["complete"])
        self.assertIn("data-no-dark", content)
        self.assertIn("data-ignore-dm", content)

        with self.assertRaisesRegex(ValueError, "section"):
            _read_wechat_compliance_spec_page("unknown")

    def test_system_rule_prompt_covers_all_official_groups_and_exemptions(self) -> None:
        prompt = RULE_PROMPT_PATH.read_text(encoding="utf-8")

        for official_key in (
            "opacity",
            "caret-color",
            "line-height",
            "width",
            "height-nodisplay",
            "text-align",
            "animate-begin",
            "pre",
            "nest-level",
            "redundant-node",
            "span-leaf",
            "node-leaf",
            "font-family",
            "darkmode-low-contrast",
            "darkmode-no-gradient",
        ):
            self.assertIn(official_key, prompt)
        for exemption in ("data-ignore-width", "data-ignore-dm", "data-no-dark"):
            self.assertIn(exemption, prompt)

        self.assertIn("isValid=null", prompt)
        self.assertIn("read_wechat_compliance_spec", prompt)
        self.assertIn("不是每轮编辑的固定步骤", prompt)
        self.assertIn("不要重复读取", prompt)
        self.assertIn("可能触发疑似误报", prompt)
        self.assertIn("同一视觉行内嵌套不同样式", prompt)
        self.assertIn("Range 可能把同一行拆成多个矩形", prompt)
        self.assertIn("实际没有多行文字重叠", prompt)
        self.assertIn("作为疑似误报静默忽略", prompt)
        self.assertIn("禁止仅为清除告警而删除嵌套的内联强调", prompt)
        self.assertIn("把局部强调改成整行同色", prompt)
        self.assertIn("无需在思考过程或普通任务的最终回复中主动强调", prompt)
        self.assertIn("仅当用户主动询问合规结论时", prompt)
        self.assertIn("不得声称该次 `isValid=true`", prompt)
        self.assertIn("无法确认实际显示正常时，不得忽略", prompt)
        self.assertNotIn("最终说明必须准确写明", prompt)
        self.assertIn("默认不创建外链跳转", prompt)
        self.assertIn("非微信官方合规规则", prompt)
        self.assertIn("不得新增 `<script>`", prompt)
        self.assertIn("内联事件属性", prompt)
        self.assertIn("`javascript:` URL", prompt)
        self.assertIn("不得新增 `<iframe>`、`<object>`", prompt)
        self.assertIn("外链 CSS 或 `<style>` 标签", prompt)
        self.assertIn("不擅自改变原文事实与语义", prompt)
        self.assertIn("不插入占位图", prompt)
        self.assertNotIn(OFFICIAL_ENGINE_COMMIT, prompt)
        self.assertNotIn("Node.js", prompt)
        self.assertNotIn("Chromium", prompt)

    def test_parses_the_official_result_without_legacy_fields(self) -> None:
        report = _parse_result(
            {
                "isValid": False,
                "inValidInfo": {
                    "width": {
                        "violateRules": "官方宽度规则",
                        "items": [
                            {
                                "paragraphIndex": "3",
                                "outerHTML": "<section style=\"width:800px\">正文</section>",
                                "rules": "不同屏幕下宽度差异",
                                "thIndex": 2,
                            }
                        ],
                    }
                },
                "warnMsgs": ["官方引擎警告"],
            }
        ).to_dict()

        self.assertEqual(report["engine"]["version"], OFFICIAL_ENGINE_VERSION)
        self.assertEqual(report["engine"]["commit"], OFFICIAL_ENGINE_COMMIT)
        self.assertFalse(report["isValid"])
        self.assertEqual(report["violations"][0]["key"], "width")
        self.assertEqual(report["violations"][0]["items"][0]["paragraphIndex"], "3")
        self.assertEqual(report["violations"][0]["items"][0]["measurements"], {"thIndex": 2})
        self.assertEqual(report["warnMsgs"], ["官方引擎警告"])
        self.assertNotIn("diagnostics", report)
        self.assertNotIn("hasError", report)
        parsed_schema = ComplianceReportRead.model_validate(report)
        self.assertEqual(parsed_schema.violations[0].key, "width")

    def test_engine_startup_error_returns_unverified(self) -> None:
        engine = OfficialComplianceEngine()
        try:
            with patch.object(engine, "_ensure_browser_on_worker", side_effect=RuntimeError("chromium missing")):
                report = engine.check("<p>正文</p>", timeout_seconds=1).to_dict()
        finally:
            engine.close()

        self.assertIsNone(report["isValid"])
        self.assertFalse(report["engine"]["available"])
        self.assertIn("chromium missing", report["engine"]["detail"])

    def test_cold_start_has_extra_budget_without_extending_warm_or_explicit_deadlines(self) -> None:
        engine = OfficialComplianceEngine()
        expected = _parse_result({"isValid": True, "inValidInfo": {}})

        def slow_check(_html: str) -> object:
            time.sleep(0.15)
            return expected

        settings = SimpleNamespace(
            WECHAT_COMPLIANCE_CHECK_TIMEOUT_SECONDS=0.05,
            WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS=0.3,
            WECHAT_COMPLIANCE_BROWSER_IDLE_SECONDS=10,
        )
        try:
            with (
                patch("app.services.wechat_compliance.get_settings", return_value=settings),
                patch.object(engine, "_check_on_worker", side_effect=slow_check),
            ):
                self.assertTrue(engine.check("<p>正文</p>").is_valid)
                engine._browser_ready.set()
                self.assertIsNone(engine.check("<p>正文</p>").is_valid)
                engine._browser_ready.clear()
                self.assertIsNone(engine.check("<p>正文</p>", timeout_seconds=0.05).is_valid)
        finally:
            engine.close()

    def test_browser_startup_timeout_cancels_launch(self) -> None:
        engine = OfficialComplianceEngine()
        launch_cancelled = threading.Event()

        class FakeChromium:
            async def launch(self, **_options):
                try:
                    await asyncio.sleep(1)
                finally:
                    launch_cancelled.set()

        class FakePlaywright:
            chromium = FakeChromium()

            async def stop(self):
                return None

        class FakeManager:
            async def start(self):
                return FakePlaywright()

        engine._event_loop = _new_browser_event_loop()
        try:
            with (
                patch("playwright.async_api.async_playwright", return_value=FakeManager()),
                patch("app.services.wechat_compliance._BUNDLE_PATH") as bundle_path,
                patch("app.services.wechat_compliance.get_settings", return_value=SimpleNamespace(
                    WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH="",
                    WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS=0.05,
                )),
            ):
                bundle_path.is_file.return_value = True
                bundle_path.read_text.return_value = "window.VerifyArticleStructure = {};"
                with self.assertRaisesRegex(RuntimeError, "Chromium 启动超过"):
                    engine._ensure_browser_on_worker()
            self.assertTrue(launch_cancelled.is_set())
            self.assertIsNone(engine._playwright)
            self.assertFalse(engine._browser_ready.is_set())
        finally:
            engine._close_on_worker()

    def test_missing_managed_browser_error_explains_runtime_user_install(self) -> None:
        engine = OfficialComplianceEngine()

        class FakeChromium:
            async def launch(self, **_options):
                raise RuntimeError(
                    "BrowserType.launch: Executable doesn't exist at "
                    "/home/www/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell"
                )

        class FakePlaywright:
            chromium = FakeChromium()

            async def stop(self):
                return None

        class FakeManager:
            async def start(self):
                return FakePlaywright()

        engine._event_loop = _new_browser_event_loop()
        try:
            with (
                patch("playwright.async_api.async_playwright", return_value=FakeManager()),
                patch("app.services.wechat_compliance._BUNDLE_PATH") as bundle_path,
                patch("app.services.wechat_compliance.get_settings", return_value=SimpleNamespace(
                    WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH="",
                    WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS=40,
                )),
            ):
                bundle_path.is_file.return_value = True
                bundle_path.read_text.return_value = "window.VerifyArticleStructure = {};"
                with self.assertRaisesRegex(RuntimeError, "install --only-shell chromium"):
                    engine._ensure_browser_on_worker()
        finally:
            engine._close_on_worker()

    def test_managed_full_chromium_override_uses_headless_shell(self) -> None:
        engine = OfficialComplianceEngine()
        expected_path = Path("/home/www/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome")

        class FakeChromium:
            executable_path = str(expected_path)

            async def launch(self, **options):
                self.launch_options = options
                return object()

        class FakePlaywright:
            def __init__(self):
                self.chromium = FakeChromium()

            async def stop(self):
                return None

        class FakeManager:
            def __init__(self):
                self.playwright = FakePlaywright()

            async def start(self):
                return self.playwright

        manager = FakeManager()
        engine._event_loop = _new_browser_event_loop()
        try:
            with (
                patch("playwright.async_api.async_playwright", return_value=manager),
                patch("app.services.wechat_compliance._BUNDLE_PATH") as bundle_path,
                patch("pathlib.Path.is_file", return_value=False),
                patch("app.services.wechat_compliance.get_settings", return_value=SimpleNamespace(
                    WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH=str(expected_path),
                    WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS=40,
                )),
            ):
                bundle_path.is_file.return_value = True
                bundle_path.read_text.return_value = "window.VerifyArticleStructure = {};"
                engine._ensure_browser_on_worker()

            self.assertEqual(manager.playwright.chromium.launch_options, {"headless": True})
        finally:
            engine._close_on_worker()

    def test_external_browser_override_is_preserved(self) -> None:
        engine = OfficialComplianceEngine()

        class FakeChromium:
            async def launch(self, **options):
                self.launch_options = options
                return object()

        class FakePlaywright:
            def __init__(self):
                self.chromium = FakeChromium()

            async def stop(self):
                return None

        class FakeManager:
            def __init__(self):
                self.playwright = FakePlaywright()

            async def start(self):
                return self.playwright

        manager = FakeManager()
        engine._event_loop = _new_browser_event_loop()
        try:
            with (
                patch("playwright.async_api.async_playwright", return_value=manager),
                patch("app.services.wechat_compliance._BUNDLE_PATH") as bundle_path,
                patch("pathlib.Path.is_file", return_value=True),
                patch("app.services.wechat_compliance.get_settings", return_value=SimpleNamespace(
                    WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH="/usr/bin/chromium",
                    WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS=40,
                )),
            ):
                bundle_path.read_text.return_value = "window.VerifyArticleStructure = {};"
                engine._ensure_browser_on_worker()

            self.assertEqual(manager.playwright.chromium.launch_options, {
                "headless": True,
                "executable_path": str(Path("/usr/bin/chromium")),
            })
        finally:
            engine._close_on_worker()

    def test_browser_segmentation_fault_has_short_actionable_error(self) -> None:
        engine = OfficialComplianceEngine()

        class FakeChromium:
            async def launch(self, **_options):
                raise RuntimeError(
                    "BrowserType.launch: Target page, context or browser has been closed\n"
                    "[pid=123] process did exit: exitCode=null, signal=SIGSEGV"
                )

        class FakePlaywright:
            chromium = FakeChromium()

            async def stop(self):
                return None

        class FakeManager:
            async def start(self):
                return FakePlaywright()

        engine._event_loop = _new_browser_event_loop()
        try:
            with (
                patch("playwright.async_api.async_playwright", return_value=FakeManager()),
                patch("app.services.wechat_compliance._BUNDLE_PATH") as bundle_path,
                patch("app.services.wechat_compliance.get_settings", return_value=SimpleNamespace(
                    WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH="",
                    WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS=40,
                )),
            ):
                bundle_path.is_file.return_value = True
                bundle_path.read_text.return_value = "window.VerifyArticleStructure = {};"
                with self.assertRaisesRegex(RuntimeError, "启动后崩溃（SIGSEGV）") as failure:
                    engine._ensure_browser_on_worker()
            self.assertNotIn("BrowserType.launch", str(failure.exception))
        finally:
            engine._close_on_worker()

    def test_worker_recreates_the_browser_after_a_transient_failure(self) -> None:
        engine = OfficialComplianceEngine()
        expected = _parse_result({"isValid": True, "inValidInfo": {}})
        try:
            with (
                patch.object(
                    engine,
                    "_check_once_on_worker",
                    side_effect=[RuntimeError("browser page closed"), expected],
                ) as check_once,
                patch.object(engine, "_dispose_browser_on_worker") as dispose_browser,
            ):
                report = engine.check("<p>正文</p>", timeout_seconds=1).to_dict()
        finally:
            engine.close()

        self.assertTrue(report["engine"]["available"])
        self.assertTrue(report["isValid"])
        self.assertEqual(check_once.call_count, 2)
        dispose_browser.assert_called_once()

    def test_deterministic_rule_error_does_not_restart_browser(self) -> None:
        engine = OfficialComplianceEngine()
        try:
            with (
                patch.object(engine, "_check_once_on_worker", side_effect=TypeError("rule defect")) as check_once,
                patch.object(engine, "_dispose_browser_on_worker") as dispose_browser,
            ):
                report = engine.check("<p>正文</p>", timeout_seconds=1).to_dict()
                self.assertEqual(check_once.call_count, 1)
                dispose_browser.assert_not_called()
        finally:
            engine.close()

        self.assertIsNone(report["isValid"])
        self.assertIn("TypeError", report["engine"]["detail"])

    def test_worker_timeout_cancels_actual_browser_coroutine(self) -> None:
        engine = OfficialComplianceEngine()
        cancelled = threading.Event()

        async def slow_evaluation(_html: str):
            try:
                await asyncio.sleep(5)
            finally:
                cancelled.set()

        def ensure_worker_loop() -> None:
            if engine._event_loop is None:
                engine._event_loop = _new_browser_event_loop()
                asyncio.set_event_loop(engine._event_loop)

        try:
            with (
                patch.object(engine, "_ensure_browser_on_worker", side_effect=ensure_worker_loop),
                patch.object(engine, "_evaluate_on_browser", side_effect=slow_evaluation),
            ):
                report = engine.check("<p>正文</p>", timeout_seconds=0.1).to_dict()
                self.assertTrue(cancelled.wait(1), "timed-out coroutine kept running")
        finally:
            engine.close()

        self.assertIsNone(report["isValid"])
        self.assertIn("未完成检测", report["engine"]["detail"])

    def test_idle_timer_releases_browser_and_respects_newly_queued_check(self) -> None:
        engine = OfficialComplianceEngine()
        expected = _parse_result({"isValid": True, "inValidInfo": {}})
        timers = []
        disposed = threading.Event()

        class FakeTimer:
            def __init__(self, _seconds, callback, args=()):
                self.callback = callback
                self.args = args
                self.cancelled = False
                timers.append(self)

            def start(self):
                return None

            def cancel(self):
                self.cancelled = True

        try:
            with (
                patch("app.services.wechat_compliance.threading.Timer", FakeTimer),
                patch.object(engine, "_check_on_worker", return_value=expected),
                patch.object(engine, "_dispose_browser_on_worker", side_effect=lambda **_kwargs: disposed.set()),
            ):
                self.assertTrue(engine.check("<p>正文</p>", timeout_seconds=1).is_valid)
                for _ in range(100):
                    if timers:
                        break
                    time.sleep(0.001)
                self.assertTrue(timers)

                first_timer = timers[-1]
                engine._executor_for_check()
                first_timer.callback(*first_timer.args)
                time.sleep(0.02)
                self.assertFalse(disposed.is_set())

                engine._check_finished(None)
                latest_timer = timers[-1]
                latest_timer.callback(*latest_timer.args)
                self.assertTrue(disposed.wait(1))
        finally:
            engine.close()

    def test_idle_cleanup_releases_browser_before_playwright_driver(self) -> None:
        engine = OfficialComplianceEngine()
        timers = []
        browser_closed = threading.Event()
        driver_stopped = threading.Event()

        class FakeTimer:
            def __init__(self, seconds, callback, args=()):
                self.seconds = seconds
                self.callback = callback
                self.args = args
                timers.append(self)

            def start(self):
                return None

            def cancel(self):
                return None

        class FakeBrowser:
            async def close(self):
                browser_closed.set()

        class FakePlaywright:
            async def stop(self):
                driver_stopped.set()

        engine._event_loop = _new_browser_event_loop()
        engine._browser = FakeBrowser()
        engine._playwright = FakePlaywright()
        engine._browser_ready.set()
        try:
            with (
                patch("app.services.wechat_compliance.threading.Timer", FakeTimer),
                patch("app.services.wechat_compliance.get_settings", return_value=SimpleNamespace(
                    WECHAT_COMPLIANCE_BROWSER_IDLE_SECONDS=10,
                    WECHAT_COMPLIANCE_DRIVER_IDLE_SECONDS=120,
                )),
            ):
                engine._executor_for_check()
                engine._check_finished(None)
                self.assertEqual(timers[0].seconds, 10)
                timers[0].callback(*timers[0].args)
                self.assertTrue(browser_closed.wait(1))
                for _ in range(100):
                    if len(timers) == 2:
                        break
                    time.sleep(0.001)
                self.assertEqual(timers[1].seconds, 110)
                self.assertFalse(driver_stopped.is_set())
                self.assertIsNotNone(engine._playwright)
                timers[1].callback(*timers[1].args)
                self.assertTrue(driver_stopped.wait(1))
        finally:
            engine.close()

    def test_empty_worker_error_still_identifies_its_exception_type(self) -> None:
        engine = OfficialComplianceEngine()
        try:
            with patch.object(engine, "_check_once_on_worker", side_effect=EOFError()):
                report = engine.check("<p>正文</p>", timeout_seconds=1).to_dict()
        finally:
            engine.close()

        self.assertIsNone(report["isValid"])
        self.assertIn("EOFError", report["engine"]["detail"])

    def test_queue_timeout_returns_unverified_without_raising(self) -> None:
        engine = OfficialComplianceEngine()
        started = threading.Event()

        def slow_check(_html: str):
            started.set()
            time.sleep(0.25)
            return _parse_result({"isValid": True, "inValidInfo": {}})

        try:
            with patch.object(engine, "_check_on_worker", side_effect=slow_check):
                report = engine.check("<p>正文</p>", timeout_seconds=0.1).to_dict()
                self.assertTrue(started.wait(0.1))
        finally:
            engine.close()

        self.assertIsNone(report["isValid"])
        self.assertFalse(report["engine"]["available"])
        self.assertIn("未完成检测", report["engine"]["detail"])

    @unittest.skipUnless(
        os.getenv("RUN_WECHAT_BROWSER_TESTS") == "1",
        "requires Playwright Chromium; set RUN_WECHAT_BROWSER_TESTS=1 after installing it",
    )
    def test_official_browser_fixtures_and_exemptions(self) -> None:
        engine = OfficialComplianceEngine()
        try:
            good = engine.check((FIXTURE_DIR / "good-responsive.html").read_text(encoding="utf-8"), timeout_seconds=20).to_dict()
            single_line = engine.check((FIXTURE_DIR / "good-line-height-single-line.html").read_text(encoding="utf-8"), timeout_seconds=20).to_dict()
            empty_paragraph = engine.check("<p></p>", timeout_seconds=20).to_dict()
            official_badcase = engine.check((FIXTURE_DIR / "bad-official-violations.html").read_text(encoding="utf-8"), timeout_seconds=20).to_dict()
            dark_html = (FIXTURE_DIR / "bad-darkmode-official.html").read_text(encoding="utf-8")
            dark = engine.check(dark_html, timeout_seconds=20).to_dict()
            ignored_width = engine.check('<section data-ignore-width style="width: 800px">豁免宽度</section>', timeout_seconds=20).to_dict()
            ignored_dark = engine.check(
                dark_html.replace(
                    'class="js_darkmode__bg__0 js_darkmode__0"',
                    'data-ignore-dm="text-bg-gradient" class="js_darkmode__bg__0 js_darkmode__0"',
                ).replace(
                    '<span leaf="">',
                    '<span leaf="" data-ignore-dm="low-contrast">',
                ),
                timeout_seconds=20,
            ).to_dict()
        finally:
            engine.close()

        for report in (good, single_line, empty_paragraph, official_badcase, dark, ignored_width, ignored_dark):
            self.assertTrue(report["engine"]["available"], report)
        self.assertTrue(good["isValid"], good)
        self.assertTrue(single_line["isValid"], single_line)
        self.assertEqual(
            {item["key"] for item in official_badcase["violations"]},
            {"caret-color", "height-nodisplay"},
        )
        self.assertTrue(
            {"darkmode-low-contrast", "darkmode-no-gradient"}.issubset(
                {item["key"] for item in dark["violations"]}
            )
        )
        self.assertNotIn("width", {item["key"] for item in ignored_width["violations"]})
        self.assertNotIn("darkmode-low-contrast", {item["key"] for item in ignored_dark["violations"]})
        self.assertNotIn("darkmode-no-gradient", {item["key"] for item in ignored_dark["violations"]})


if __name__ == "__main__":
    unittest.main()
