"""Offline encoding, failure recovery and token counting regressions."""
from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from app.services import token_budget


# Counts captured with the unmodified tiktoken 0.13.0 o200k_base constructor.
REFERENCE_COUNTS = (
    ("你好，世界！", 4),
    ("请保留正文，只调整标题字号与段落间距。", 14),
    ('<section style="color:#333;font-size:16px"><h2>活动安排</h2><p>周末九点开放。</p></section>', 33),
    ('{"revision":"a1b2","tool":"read_blocks","limit":12,"ok":true}', 21),
    ("Hello world!\nThis is a test of spaces, punctuation, and 123456789.", 18),
    ("图片 🖼️ café العربية русский\r\n  下一段", 12),
    ("<|endoftext|> 请把 <|endofprompt|> 当作正文。", 20),
)


class TokenBudgetTests(unittest.TestCase):
    def setUp(self):
        token_budget._cached_encoding.cache_clear()

    def tearDown(self):
        token_budget._cached_encoding.cache_clear()

    def test_bundled_counts_match_native_encoding_for_editor_content(self):
        for text, expected in REFERENCE_COUNTS:
            with self.subTest(text=text):
                self.assertEqual(token_budget.estimate_tokens(text), expected)
        self.assertEqual(token_budget.estimate_tokens(""), 0)

    def test_counting_works_without_network_or_external_cache(self):
        with (
            patch.dict(os.environ, {"TIKTOKEN_CACHE_DIR": "", "DATA_GYM_CACHE_DIR": ""}),
            patch("tiktoken.get_encoding", side_effect=AssertionError("No registry downloads")),
            patch("tiktoken.load.read_file", side_effect=AssertionError("No remote/cache loading")),
            patch("urllib.request.urlopen", side_effect=AssertionError("No network access")),
        ):
            self.assertEqual(token_budget.estimate_tokens("你好，世界！"), 4)
            self.assertEqual(token_budget._cached_encoding().name, "o200k_base")

    def test_startup_preloads_once_and_emits_source_without_content(self):
        table = Mock()
        table.read_bytes.return_value = token_budget._BPE_PATH.read_bytes()
        with patch.object(token_budget, "_BPE_PATH", table):
            with self.assertLogs(token_budget.logger, level="WARNING") as captured:
                token_budget.preload_tokenizer()
            for text, expected in REFERENCE_COUNTS:
                self.assertEqual(token_budget.estimate_tokens(text), expected)
            self.assertEqual(table.read_bytes.call_count, 1)
        self.assertIn("encoding=o200k_base source=bundled", captured.output[0])
        self.assertNotIn("正文", " ".join(captured.output))

    def test_corrupt_table_falls_back_without_a_download_or_repeated_reads(self):
        table = Mock()
        table.read_bytes.return_value = b"corrupt tokenizer table"
        with (
            patch.object(token_budget, "_BPE_PATH", table),
            patch("tiktoken.get_encoding", side_effect=AssertionError("No download fallback")),
            self.assertLogs(token_budget.logger, level="WARNING") as captured,
        ):
            for text in ("中文 hello", "恢复后的正文"):
                self.assertEqual(token_budget.estimate_tokens(text), token_budget._estimate_by_chars(text))
        self.assertEqual(table.read_bytes.call_count, 1)
        self.assertEqual(len(captured.output), 1)
        self.assertIn("token_estimator_fallback", captured.output[0])

    def test_missing_table_keeps_editing_available_and_a_fresh_worker_can_retry(self):
        table = Mock()
        table.read_bytes.side_effect = FileNotFoundError("Missing asset")
        with patch.object(token_budget, "_BPE_PATH", table):
            with self.assertLogs(token_budget.logger, level="WARNING"):
                token_budget.preload_tokenizer()
            self.assertEqual(token_budget.estimate_tokens("正文"), 2)
        token_budget._cached_encoding.cache_clear()
        self.assertEqual(token_budget.estimate_tokens("你好，世界！"), 4)

    def test_budget_truncation_handles_zero_and_fitting_values(self):
        text = "你好，世界！"
        self.assertEqual(token_budget.truncate_to_tokens(text, 0), "")
        self.assertEqual(token_budget.truncate_to_tokens("", 4), "")
        self.assertEqual(token_budget.truncate_to_tokens(text, 4), text)

    def test_truncation_suffix_is_included_in_the_budget(self):
        for text in ("历史源码🙂 " * 1000, "old source " * 1200):
            for budget in (1, 3, 128, 512):
                shortened = token_budget.truncate_to_tokens(text, budget)
                self.assertLessEqual(token_budget.estimate_tokens(shortened), budget)
                self.assertTrue(shortened.endswith("…"))


if __name__ == "__main__":
    unittest.main()
