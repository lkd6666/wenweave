from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.models  # noqa: F401 - register every table.
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.model_call_record import ModelCallRecord, ModelCallSource, ModelCallStatus
from app.services.model_call_accounting import ModelCallTracker, usage_from_message


class ModelCallAccountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_usage_keeps_cache_read_and_write_separate(self) -> None:
        message = AIMessage(content="ok")
        message.usage_metadata = {
            "input_tokens": 1000,
            "output_tokens": 80,
            "input_token_details": {"cache_read": 700, "cache_creation": 120},
        }

        usage = usage_from_message(message)

        assert usage is not None
        self.assertEqual(usage.cache_read_tokens, 700)
        self.assertEqual(usage.cache_write_tokens, 120)

    def test_usage_reads_openai_response_metadata_when_the_sdk_does_not_normalise_it(self) -> None:
        message = AIMessage(content="ok")
        message.response_metadata = {
            "token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 80,
                "prompt_tokens_details": {"cached_tokens": 700},
            }
        }

        usage = usage_from_message(message)

        assert usage is not None
        self.assertEqual(usage.input_tokens, 1000)
        self.assertEqual(usage.output_tokens, 80)
        self.assertEqual(usage.cache_read_tokens, 700)
        self.assertEqual(usage.cache_write_tokens, 0)

    def test_usage_reads_anthropic_native_cache_fields(self) -> None:
        message = AIMessage(content="ok")
        message.response_metadata = {
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 80,
                "cache_read_input_tokens": 700,
                "cache_creation_input_tokens": 120,
            }
        }

        usage = usage_from_message(message)

        assert usage is not None
        self.assertEqual(usage.cache_read_tokens, 700)
        self.assertEqual(usage.cache_write_tokens, 120)
        self.assertEqual(usage.input_tokens, 1820)

    def test_service_tiers_use_sdk_cache_fields(self) -> None:
        from langchain_openai.chat_models.base import _create_usage_metadata_responses
        native = {"input_tokens": 1000, "output_tokens": 80,
                  "input_tokens_details": {"cached_tokens": 700, "cache_write_tokens": 120}}
        for tier in ("default", "priority", "flex"):
            with self.subTest(tier=tier):
                usage = usage_from_message(SimpleNamespace(usage_metadata=_create_usage_metadata_responses(native, tier)))
                self.assertEqual((usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens), (1000, 700, 120))

    def test_metadata_fills_only_missing_fields(self) -> None:
        message = SimpleNamespace(
            usage_metadata={"input_tokens": 1000, "output_tokens": 80, "input_token_details": {"cache_read": 0}},
            response_metadata={"usage": {"input_tokens": 1000, "output_tokens": 80,
                                          "input_tokens_details": {"cached_tokens": 700, "cache_write_tokens": 120}}},
        )
        usage = usage_from_message(message)
        self.assertEqual((usage.cache_read_tokens, usage.cache_write_tokens), (0, 120))
        message.usage_metadata.pop("input_token_details")
        usage = usage_from_message(message)
        self.assertEqual((usage.cache_read_tokens, usage.cache_write_tokens), (700, 120))

    def test_cache_aliases_are_not_added_twice(self) -> None:
        usage = usage_from_message(SimpleNamespace(usage_metadata={
            "input_tokens": 1000, "output_tokens": 80,
            "input_token_details": {"cache_read": 700, "priority_cache_read": 700,
                                    "cache_creation": 120, "priority_cache_creation": 120},
            "cached_tokens": 700,
        }))
        self.assertEqual((usage.cache_read_tokens, usage.cache_write_tokens), (700, 120))

    def test_deepseek_cache_misses_are_not_cache_writes(self) -> None:
        usage = usage_from_message(SimpleNamespace(response_metadata={"token_usage": {
            "prompt_tokens": 1000, "completion_tokens": 80,
            "prompt_cache_hit_tokens": 700, "prompt_cache_miss_tokens": 300,
        }}))
        self.assertEqual((usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens), (1000, 700, 0))

    def test_anthropic_normalised_totals_are_not_added_twice(self) -> None:
        usage = usage_from_message(SimpleNamespace(
            usage_metadata={"input_tokens": 1820, "output_tokens": 80,
                            "input_token_details": {"cache_read": 700, "cache_creation": 120}},
            response_metadata={"usage": {"input_tokens": 1000, "output_tokens": 80,
                                         "cache_read_input_tokens": 700, "cache_creation_input_tokens": 120}},
        ))
        self.assertEqual((usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens), (1820, 700, 120))

    def test_anthropic_fully_cached_input_is_reported(self) -> None:
        usage = usage_from_message(SimpleNamespace(response_metadata={"usage": {
            "input_tokens": 0, "output_tokens": 80, "cache_read_input_tokens": 700,
        }}))
        self.assertEqual(usage.input_tokens, 700)

    def test_invalid_cache_fields_can_fall_back_to_native_metadata(self) -> None:
        usage = usage_from_message(SimpleNamespace(
            usage_metadata={"input_tokens": 1000, "output_tokens": 80,
                            "input_token_details": {"cache_read": True, "cache_creation": -1}},
            response_metadata={"usage": {"input_tokens_details": {"cached_tokens": 700, "cache_write_tokens": 120}}},
        ))
        self.assertEqual((usage.cache_read_tokens, usage.cache_write_tokens), (700, 120))

    def test_aggregate_zero_precedes_tier_aliases_in_the_same_usage(self) -> None:
        usage = usage_from_message(SimpleNamespace(usage_metadata={
            "input_tokens": 1000, "output_tokens": 0,
            "input_token_details": {"priority_cache_read": 700, "priority_cache_creation": 120},
            "cache_read_tokens": 0, "cache_write_tokens": 0,
        }))
        self.assertEqual((usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens), (0, 0, 0))

    def test_empty_normalised_details_still_mark_an_inclusive_input_total(self) -> None:
        usage = usage_from_message(SimpleNamespace(usage_metadata={
            "input_tokens": 1000, "output_tokens": 80, "input_token_details": {},
            "cache_read_input_tokens": 700, "cache_creation_input_tokens": 120,
        }))
        self.assertEqual((usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens), (1000, 700, 120))

    def test_tracker_persists_unreported_and_failed_attempts(self) -> None:
        with patch("app.services.model_call_accounting.SessionLocal", return_value=self.db):
            ModelCallTracker(
                model_id=7,
                user_id=3,
                source=ModelCallSource.AGENT,
                source_id="run-1",
            ).complete(AIMessage(content="no provider usage"))
            ModelCallTracker(
                model_id=7,
                user_id=3,
                source=ModelCallSource.AGENT_RUNTIME_COMPACTION,
                source_id="run-1",
            ).fail(RuntimeError("upstream unavailable"))

        rows = self.db.query(ModelCallRecord).order_by(ModelCallRecord.id).all()
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0].usage_reported)
        self.assertIsNone(rows[0].input_tokens)
        self.assertEqual(rows[0].status, ModelCallStatus.COMPLETED)
        self.assertEqual(rows[1].status, ModelCallStatus.FAILED)
        self.assertEqual(rows[1].error_message, "upstream unavailable")
        self.assertIsNotNone(rows[0].started_at)

    def test_tracker_persists_running_record_then_updates_the_same_row(self) -> None:
        with patch("app.services.model_call_accounting.SessionLocal", return_value=self.db):
            tracker = ModelCallTracker(
                model_id=7,
                user_id=3,
                source=ModelCallSource.AGENT,
                source_id="run-inflight",
            )
            row = self.db.get(ModelCallRecord, tracker.record_id)
            assert row is not None
            self.assertEqual(row.status, ModelCallStatus.RUNNING)
            self.assertIsNone(row.finished_at)

            tracker.complete(AIMessage(content="done"))

        rows = self.db.query(ModelCallRecord).filter(ModelCallRecord.source_id == "run-inflight").all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, ModelCallStatus.COMPLETED)
        self.assertIsNotNone(rows[0].finished_at)
