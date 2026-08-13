"""Provider-reported token usage replaces the tiktoken estimate when available.

``estimate_tokens`` prices Chinese prose and HTML with a tokenizer that matches
neither provider exactly. These cases lock in that real usage is preferred when
returned, and that a missing or zero-filled usage block falls back to the
estimate instead of reporting a bogus zero.
"""
from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage

from app.services.chat_agent import _usage_from_message


def _message(usage: dict | None) -> AIMessage:
    message = AIMessage(content="已完成排版调整")
    message.usage_metadata = usage  # type: ignore[assignment]
    return message


class TokenAccountingTests(unittest.TestCase):
    def test_reported_usage_is_returned(self) -> None:
        usage = _usage_from_message(
            _message({"input_tokens": 9000, "output_tokens": 420, "total_tokens": 9420})
        )

        assert usage is not None
        self.assertEqual(usage["input_tokens"], 9000)
        self.assertEqual(usage["output_tokens"], 420)
        self.assertEqual(usage["total_tokens"], 9420)

    def test_cache_hits_exclude_cache_creation_tokens(self) -> None:
        usage = _usage_from_message(
            _message(
                {
                    "input_tokens": 9000,
                    "output_tokens": 100,
                    "total_tokens": 9100,
                    "input_token_details": {"cache_read": 8000, "cache_creation": 100},
                }
            )
        )

        assert usage is not None
        self.assertEqual(usage["cached_input_tokens"], 8000)
        self.assertEqual(usage["cache_read_tokens"], 8000)
        self.assertEqual(usage["cache_write_tokens"], 100)

    def test_total_is_derived_when_the_provider_omits_it(self) -> None:
        usage = _usage_from_message(_message({"input_tokens": 500, "output_tokens": 60}))

        assert usage is not None
        self.assertEqual(usage["total_tokens"], 560)

    def test_missing_usage_falls_back_to_the_estimate(self) -> None:
        self.assertIsNone(_usage_from_message(_message(None)))
        self.assertIsNone(_usage_from_message(AIMessage(content="无用量字段")))

    def test_zero_filled_usage_is_rejected_rather_than_reported(self) -> None:
        """全零用量会把上下文仪表清零，并把这个空值标记为「已实测」。"""
        self.assertIsNone(
            _usage_from_message(_message({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}))
        )

    def test_non_integer_usage_is_rejected(self) -> None:
        self.assertIsNone(
            _usage_from_message(_message({"input_tokens": "9000", "output_tokens": 420}))
        )


if __name__ == "__main__":
    unittest.main()
