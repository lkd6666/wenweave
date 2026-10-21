"""Official WeChat article-structure verification adapter.

The only rules source for this module is the vendored
``verify-article-structure-spec`` browser bundle. Its layout and Dark Mode
rules require a real browser, so this adapter owns one lazy, process-local
Playwright worker and serializes verification work through that worker.
"""
from __future__ import annotations

import atexit
import asyncio
import logging
import sys
import threading
from time import monotonic
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.core.config import get_settings

logger = logging.getLogger(__name__)

OFFICIAL_ENGINE_VERSION = "0.2.16"
OFFICIAL_ENGINE_COMMIT = "fa69e37341c86bfec4c8c533845910511e534c0c"
OFFICIAL_ENGINE_REPOSITORY = "https://github.com/wechatjs/verify-article-structure-spec"
_BUNDLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "_third_party"
    / "verify-article-structure-spec"
    / "cli"
    / "dist"
    / "verify-article-structure.browser.js"
)


@dataclass(frozen=True)
class ComplianceEngineStatus:
    version: str = OFFICIAL_ENGINE_VERSION
    commit: str = OFFICIAL_ENGINE_COMMIT
    repository: str = OFFICIAL_ENGINE_REPOSITORY
    available: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "commit": self.commit,
            "repository": self.repository,
            "available": self.available,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ComplianceViolationItem:
    paragraph_index: int | str | None = None
    outer_html: str = ""
    rules: str = ""
    measurements: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paragraphIndex": self.paragraph_index,
            "outerHTML": self.outer_html,
            "rules": self.rules,
            "measurements": self.measurements,
        }


@dataclass(frozen=True)
class ComplianceViolation:
    key: str
    message: str
    items: list[ComplianceViolationItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "message": self.message,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class ComplianceReport:
    """Public report returned by the official checker.

    ``is_valid`` is ``None`` only when the checker could not run. Consumers
    must not treat that state as a successful verification.
    """

    engine: ComplianceEngineStatus
    is_valid: bool | None
    violations: list[ComplianceViolation] = field(default_factory=list)
    warn_msgs: list[str] = field(default_factory=list)

    @classmethod
    def unavailable(cls, detail: str) -> "ComplianceReport":
        return cls(
            engine=ComplianceEngineStatus(available=False, detail=detail),
            is_valid=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine.to_dict(),
            "isValid": self.is_valid,
            "violations": [violation.to_dict() for violation in self.violations],
            "warnMsgs": self.warn_msgs,
        }


def _json_safe(value: Any) -> Any:
    """Retain JSON data returned by the official engine and drop DOM handles."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if str(key) != "node"
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _parse_item(raw: Mapping[str, Any]) -> ComplianceViolationItem:
    measurements = {
        str(key): _json_safe(value)
        for key, value in raw.items()
        if key not in {"paragraphIndex", "outerHTML", "rules", "node"}
    }
    return ComplianceViolationItem(
        paragraph_index=raw.get("paragraphIndex"),
        outer_html=str(raw.get("outerHTML") or ""),
        rules=str(raw.get("rules") or ""),
        measurements=measurements,
    )


def _parse_result(raw: Mapping[str, Any]) -> ComplianceReport:
    invalid_info = raw.get("inValidInfo")
    violations: list[ComplianceViolation] = []
    if isinstance(invalid_info, Mapping):
        for key, entry in invalid_info.items():
            if not isinstance(entry, Mapping):
                continue
            raw_items = entry.get("items")
            items = [_parse_item(item) for item in raw_items if isinstance(item, Mapping)] if isinstance(raw_items, list) else []
            violations.append(
                ComplianceViolation(
                    key=str(key),
                    message=str(entry.get("violateRules") or entry.get("message") or ""),
                    items=items,
                )
            )
    warn_msgs = raw.get("warnMsgs")
    return ComplianceReport(
        engine=ComplianceEngineStatus(),
        is_valid=bool(raw.get("isValid")) and not violations,
        violations=violations,
        warn_msgs=[str(item) for item in warn_msgs] if isinstance(warn_msgs, list) else [],
    )


def _new_browser_event_loop() -> asyncio.AbstractEventLoop:
    """Create a worker loop that can launch Playwright's driver process.

    Uvicorn's Windows reload supervisor installs a Selector event-loop policy.
    That loop cannot create subprocesses, and Playwright otherwise inherits it
    even inside this dedicated worker thread.  The browser worker owns this
    loop, so selecting Proactor locally avoids changing the application's
    process-wide asyncio policy.
    """
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()


class OfficialComplianceEngine:
    """A single-thread Playwright owner for the official browser rule bundle."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._playwright: Any = None
        self._browser: Any = None
        self._browser_ready = threading.Event()
        self._bundle_source: str | None = None
        self._closed = False
        self._active_checks = 0
        self._idle_timer: threading.Timer | None = None
        self._activity_generation = 0
        self._worker_timeout_seconds = 0.0

    def check(self, html: str, timeout_seconds: float | None = None) -> ComplianceReport:
        settings = get_settings()
        timeout = timeout_seconds if timeout_seconds is not None else settings.WECHAT_COMPLIANCE_CHECK_TIMEOUT_SECONDS
        startup_timeout = settings.WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS
        # The regular timeout protects rule execution. A cold browser gets a
        # separate launch budget; explicit caller deadlines retain their meaning.
        cold_start = timeout_seconds is None and not self._browser_ready.is_set()
        result_timeout = max(0.1, timeout) + (startup_timeout + 2 if cold_start else 0)
        try:
            executor = self._executor_for_check()
        except RuntimeError as exc:
            return ComplianceReport.unavailable(str(exc))
        try:
            future: Future[ComplianceReport] = executor.submit(
                self._run_check_job, html, max(0.1, timeout)
            )
        except Exception as exc:
            self._check_finished(None)
            detail = str(exc).strip()
            suffix = f"{type(exc).__name__}{f'：{detail}' if detail else ''}"
            logger.warning(
                "wechat_compliance_submit_failed type=%s detail=%s",
                type(exc).__name__,
                detail,
                exc_info=True,
            )
            return ComplianceReport.unavailable(f"官方微信合规引擎不可用：{suffix}")
        future.add_done_callback(self._check_finished)
        try:
            return future.result(timeout=result_timeout)
        except FutureTimeoutError:
            future.cancel()
            detail = f"官方微信合规引擎在 {result_timeout:g} 秒内未完成检测；文章未验证。"
            logger.warning("wechat_compliance_timeout timeout_seconds=%s cold_start=%s", result_timeout, cold_start)
            return ComplianceReport.unavailable(detail)
        except Exception as exc:  # Worker errors must never block article editing.
            # Some browser-process failures stringify to an empty value.  The
            # exception type is still actionable in the UI and in persisted
            # reports, unlike a dangling colon with no diagnostic.
            detail = str(exc).strip()
            suffix = f"{type(exc).__name__}{f'：{detail}' if detail else ''}"
            logger.warning("wechat_compliance_failed type=%s detail=%s", type(exc).__name__, detail, exc_info=True)
            return ComplianceReport.unavailable(f"官方微信合规引擎不可用：{suffix}")

    def close(self) -> None:
        with self._lock:
            executor = self._executor
            idle_timer, self._idle_timer = self._idle_timer, None
            if idle_timer is not None:
                idle_timer.cancel()
            if self._closed or executor is None:
                self._closed = True
                return
            self._closed = True
        try:
            executor.submit(self._close_on_worker).result(timeout=10)
        except RuntimeError as exc:
            # Python shuts ThreadPoolExecutor workers down before ordinary
            # atexit callbacks.  At that point there is no worker left that
            # can safely own Playwright cleanup, and retrying only emits a
            # misleading shutdown failure.
            if "cannot schedule new futures after shutdown" not in str(exc):
                logger.warning("wechat_compliance_close_failed", exc_info=True)
        except Exception:
            logger.warning("wechat_compliance_close_failed", exc_info=True)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            with self._lock:
                self._executor = None

    def _executor_for_check(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._closed:
                raise RuntimeError("官方微信合规引擎已经关闭")
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wechat-compliance")
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._activity_generation += 1
            self._active_checks += 1
            return self._executor

    def _run_check_job(self, html: str, timeout_seconds: float) -> ComplianceReport:
        self._worker_timeout_seconds = timeout_seconds
        return self._check_on_worker(html)

    def _check_finished(self, _future: Future[ComplianceReport] | None) -> None:
        with self._lock:
            self._active_checks = max(0, self._active_checks - 1)
            if self._closed or self._active_checks or self._executor is None:
                return
            idle_seconds = max(10, int(get_settings().WECHAT_COMPLIANCE_BROWSER_IDLE_SECONDS))
            generation = self._activity_generation
            timer = threading.Timer(idle_seconds, self._dispose_idle_browser, args=(generation, False))
            timer.daemon = True
            self._idle_timer = timer
            timer.start()

    def _dispose_idle_browser(self, generation: int, stop_playwright: bool = False) -> None:
        with self._lock:
            executor = self._executor
            if (
                self._closed
                or self._active_checks
                or executor is None
                or generation != self._activity_generation
            ):
                return
            self._idle_timer = None
        try:
            executor.submit(self._dispose_browser_if_still_idle_on_worker, generation, stop_playwright)
        except RuntimeError:
            return

    def _dispose_browser_if_still_idle_on_worker(self, generation: int, stop_playwright: bool = False) -> None:
        # The timer can enqueue cleanup just before a new check arrives. Check
        # the generation again on the owning worker so queued work never tears
        # down the browser needed by a newly submitted detection.
        with self._lock:
            if (
                self._closed
                or self._active_checks
                or generation != self._activity_generation
            ):
                return
        self._dispose_browser_on_worker(stop_playwright=stop_playwright)
        if stop_playwright or self._playwright is None:
            return
        settings = get_settings()
        browser_idle = max(10, int(settings.WECHAT_COMPLIANCE_BROWSER_IDLE_SECONDS))
        driver_idle = max(browser_idle, int(settings.WECHAT_COMPLIANCE_DRIVER_IDLE_SECONDS))
        remaining = driver_idle - browser_idle
        if remaining <= 0:
            self._dispose_browser_on_worker()
            return
        with self._lock:
            if self._closed or self._active_checks or generation != self._activity_generation:
                return
            timer = threading.Timer(remaining, self._dispose_idle_browser, args=(generation, True))
            timer.daemon = True
            self._idle_timer = timer
            timer.start()

    def _ensure_browser_on_worker(self) -> None:
        if self._browser is not None:
            return
        if not _BUNDLE_PATH.is_file():
            raise RuntimeError(f"未找到官方规则 bundle：{_BUNDLE_PATH}")
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("未安装 Playwright；请安装后运行 python -m playwright install chromium") from exc

        settings = get_settings()
        self._bundle_source = _BUNDLE_PATH.read_text(encoding="utf-8")
        if self._event_loop is None:
            self._event_loop = _new_browser_event_loop()
            asyncio.set_event_loop(self._event_loop)
        launch_options: dict[str, Any] = {"headless": True}
        try:
            startup_deadline = monotonic() + settings.WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS
            if self._playwright is None:
                self._playwright = self._event_loop.run_until_complete(
                    asyncio.wait_for(async_playwright().start(), timeout=max(0.1, startup_deadline - monotonic()))
                )
            configured_executable = settings.WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH.strip()
            if configured_executable:
                executable = Path(configured_executable)
                # Earlier deployments pinned Playwright's full managed Chrome
                # here to work around a missing headless shell. That binary
                # can crash at startup on small Linux hosts. Managed browser
                # selection belongs to Playwright; preserve this setting only
                # for genuinely external browser installations.
                if "ms-playwright" in executable.parts and any(
                    part.startswith("chromium-") for part in executable.parts
                ):
                    logger.warning(
                        "wechat_compliance_ignoring_managed_chromium_override path=%s",
                        executable,
                    )
                else:
                    if not executable.is_file():
                        raise RuntimeError(
                            "WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH 指向的浏览器不存在："
                            f"{executable}"
                        )
                    launch_options["executable_path"] = str(executable)
            self._browser = self._event_loop.run_until_complete(
                asyncio.wait_for(
                    self._playwright.chromium.launch(**launch_options),
                    timeout=max(0.1, startup_deadline - monotonic()),
                )
            )
            self._browser_ready.set()
        except Exception as exc:
            self._browser_ready.clear()
            try:
                if self._playwright is not None:
                    self._event_loop.run_until_complete(self._playwright.stop())
            except Exception:
                logger.debug("wechat_compliance_playwright_stop_after_launch_failed", exc_info=True)
            self._playwright = None
            detail = str(exc)
            if isinstance(exc, TimeoutError):
                raise RuntimeError(
                    f"Chromium 启动超过 {settings.WECHAT_COMPLIANCE_BROWSER_STARTUP_TIMEOUT_SECONDS:g} 秒；"
                    "本次文章未验证。"
                ) from exc
            if "Executable doesn't exist" in detail and "chromium_headless_shell" in detail:
                raise RuntimeError(
                    "缺少与当前 Playwright 版本匹配的 Chromium headless shell。"
                    "请以运行后端的同一系统用户，在当前生产虚拟环境执行 "
                    "`python -m playwright install --only-shell chromium`，然后重启后端。"
                ) from exc
            if "SIGSEGV" in detail:
                raise RuntimeError(
                    "Chromium 启动后崩溃（SIGSEGV）；请检查生产环境的浏览器依赖和可用内存。"
                    "完整启动日志已记录在后端日志中。"
                ) from exc
            raise

    def _check_on_worker(self, html: str) -> ComplianceReport:
        """Run one check, recovering once from a broken persistent browser.

        Chromium may terminate a page while the long-lived process itself is
        still present.  A healthy next browser instance is then sufficient;
        retaining the old handle would make every subsequent article report
        as unverified until the application is restarted.
        """
        for attempt in range(2):
            try:
                return self._check_once_on_worker(html)
            except Exception as exc:
                recoverable = self._is_browser_process_failure(exc)
                logger.warning(
                    "wechat_compliance_worker_attempt_failed attempt=%s/2; recreating_browser=%s",
                    attempt + 1,
                    attempt == 0 and recoverable,
                    exc_info=True,
                )
                if attempt or not recoverable:
                    raise
                self._dispose_browser_on_worker()
        raise RuntimeError("官方微信合规引擎未执行检测")  # pragma: no cover - loop always returns or raises.

    @staticmethod
    def _is_browser_process_failure(exc: BaseException) -> bool:
        if isinstance(exc, (EOFError, ConnectionError, BrokenPipeError)):
            return True
        detail = f"{type(exc).__name__}: {exc}".lower()
        if "typeerror" in detail or "referenceerror" in detail or "syntaxerror" in detail:
            return False
        return any(
            marker in detail
            for marker in (
                "browser page closed",
                "target closed",
                "browser has been closed",
                "browser closed",
                "connection closed",
                "connection reset",
                "browser crashed",
                "page crashed",
            )
        )

    def _check_once_on_worker(self, html: str) -> ComplianceReport:
        self._ensure_browser_on_worker()
        assert self._event_loop is not None
        check = self._evaluate_on_browser(html)
        if self._worker_timeout_seconds > 0:
            check = asyncio.wait_for(check, timeout=self._worker_timeout_seconds)
        return self._event_loop.run_until_complete(check)

    async def _evaluate_on_browser(self, html: str) -> ComplianceReport:
        page: Any | None = None
        try:
            page = await self._browser.new_page(viewport={"width": 677, "height": 800})
            await page.add_script_tag(content=self._bundle_source)
            raw = await page.evaluate(
                """async (articleHtml) => {
                    const container = document.createElement('div');
                    container.innerHTML = articleHtml;
                    return await window.VerifyArticleStructure.verifyArticleStructure(container);
                }""",
                html,
            )
            if not isinstance(raw, Mapping):
                raise RuntimeError("官方引擎返回了无效结果")
            return _parse_result(raw)
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    # A closed/crashed browser can make page.close() throw
                    # after a successful evaluation. The next attempt above
                    # owns recovery; do not turn a valid official result into
                    # a false "unverified" report merely during cleanup.
                    logger.debug("wechat_compliance_page_close_failed", exc_info=True)

    def _dispose_browser_on_worker(self, *, stop_playwright: bool = True) -> None:
        """Release Chromium; retain the smaller driver until its own idle limit."""
        browser, self._browser = self._browser, None
        self._browser_ready.clear()
        self._bundle_source = None
        try:
            if browser is not None and self._event_loop is not None:
                self._event_loop.run_until_complete(browser.close())
        except Exception:
            logger.debug("wechat_compliance_browser_close_failed", exc_info=True)
        finally:
            if stop_playwright:
                playwright, self._playwright = self._playwright, None
                if playwright is not None and self._event_loop is not None:
                    try:
                        self._event_loop.run_until_complete(playwright.stop())
                    except Exception:
                        logger.debug("wechat_compliance_playwright_stop_failed", exc_info=True)

    def _close_on_worker(self) -> None:
        self._dispose_browser_on_worker()
        event_loop, self._event_loop = self._event_loop, None
        if event_loop is not None:
            try:
                event_loop.run_until_complete(event_loop.shutdown_asyncgens())
            finally:
                asyncio.set_event_loop(None)
                event_loop.close()


_ENGINE_LOCK = threading.Lock()
_ENGINE: OfficialComplianceEngine | None = None


def get_official_compliance_engine() -> OfficialComplianceEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = OfficialComplianceEngine()
        return _ENGINE


def close_official_compliance_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        engine = _ENGINE
        _ENGINE = None
    if engine is not None:
        engine.close()


def run_compliance_check(html: str, timeout_seconds: float | None = None) -> ComplianceReport:
    """Run the full official checker without enforcing the result."""
    return get_official_compliance_engine().check(html, timeout_seconds=timeout_seconds)


atexit.register(close_official_compliance_engine)
