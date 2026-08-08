import logging
import unittest

from app.main import _SuccessfulReadAccessLogFilter, _timestamped_log_formatter
from app.services.runtime_diagnostics import log_process_memory


class WorkerLoggingTests(unittest.TestCase):
    def _access_record(self, method: str, status_code: int) -> logging.LogRecord:
        return logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %s',
            args=("127.0.0.1:1234", method, "/api/health/ready", "1.1", status_code),
            exc_info=None,
        )

    def test_timestamp_formatter_includes_time_zone_pid_and_logger(self) -> None:
        record = logging.LogRecord(
            name="app.services.agent_run_manager",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="agent_run_event_sequence_collision_retry",
            args=(),
            exc_info=None,
        )

        rendered = _timestamped_log_formatter().format(record)

        self.assertRegex(rendered, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{4} WARNING \[pid=\d+\]")
        self.assertIn("app.services.agent_run_manager", rendered)
        self.assertTrue(rendered.endswith("agent_run_event_sequence_collision_retry"))

    def test_hides_successful_read_access_logs(self) -> None:
        log_filter = _SuccessfulReadAccessLogFilter()

        self.assertFalse(log_filter.filter(self._access_record("GET", 200)))
        self.assertFalse(log_filter.filter(self._access_record("HEAD", 304)))
        self.assertFalse(log_filter.filter(self._access_record("OPTIONS", 204)))

    def test_keeps_failed_reads_and_write_access_logs(self) -> None:
        log_filter = _SuccessfulReadAccessLogFilter()

        self.assertTrue(log_filter.filter(self._access_record("GET", 500)))
        self.assertTrue(log_filter.filter(self._access_record("POST", 200)))

    def test_memory_log_contains_stage_worker_run_and_swap_fields(self) -> None:
        logger = logging.getLogger("runtime-diagnostics-test")
        with self.assertLogs(logger, level="INFO") as captured:
            log_process_memory(
                logger,
                stage="model_start",
                worker_id="worker-test",
                run_id="run-test",
                turn=2,
            )

        self.assertIn("worker_memory stage=model_start", captured.output[0])
        self.assertIn("worker_id=worker-test", captured.output[0])
        self.assertIn("run_id=run-test", captured.output[0])
        self.assertIn("rss_kib=", captured.output[0])
        self.assertIn("swap_kib=", captured.output[0])
