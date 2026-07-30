import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.ai_providers import _model_discovery_item, _sync_default_discovered_budgets
from app.db.base import Base
from app.models.ai_model import AIModel


class ModelDiscoveryBudgetTests(unittest.TestCase):
    def test_provider_context_and_output_are_used_for_recommended_budget(self) -> None:
        result = _model_discovery_item(
            {
                "model_name": "vendor/long-context",
                "metadata": {
                    "context_length": 128000,
                    "top_provider": {"max_completion_tokens": 8192},
                },
            },
            None,
            "供应商接口",
        )

        self.assertEqual(result.context_window_tokens, 128000)
        self.assertEqual(result.max_output_tokens, 8192)
        self.assertEqual(result.context_compaction_threshold_tokens, 119808)
        self.assertEqual(result.context_window_source, "供应商接口")
        self.assertLessEqual(result.tool_result_max_tokens, result.context_compaction_threshold_tokens)

    def test_gemini_style_limits_are_recognized(self) -> None:
        result = _model_discovery_item(
            {
                "model_name": "gemini-example",
                "metadata": {"inputTokenLimit": 1048576, "outputTokenLimit": 65536},
            },
            None,
            "供应商接口",
        )

        self.assertEqual(result.context_window_tokens, 1048576)
        self.assertEqual(result.max_output_tokens, 65536)
        self.assertEqual(result.context_compaction_threshold_tokens, 983040)

    def test_missing_provider_capability_is_labeled_as_conservative_default(self) -> None:
        result = _model_discovery_item(
            {"model_name": "custom-model", "metadata": {}},
            None,
            "供应商接口",
        )

        self.assertEqual(result.context_window_tokens, 32768)
        self.assertEqual(result.context_compaction_threshold_tokens, 24576)
        self.assertEqual(result.context_window_source, "保守默认值")

    def test_deepseek_v4_catalogue_fills_one_million_context_without_provider_metadata(self) -> None:
        result = _model_discovery_item(
            {"model_name": "deepseek-v4-pro", "metadata": {}},
            None,
            "供应商接口",
        )

        self.assertEqual(result.context_window_tokens, 1_000_000)
        self.assertEqual(result.max_output_tokens, 384_000)
        self.assertEqual(result.context_compaction_threshold_tokens, 616_000)
        self.assertEqual(result.tool_result_max_tokens, 16_384)
        self.assertEqual(result.context_window_source, "内置预设")

    def test_known_long_context_catalogue_entries_do_not_fall_back_to_32k(self) -> None:
        cases = {
            "qwen3.7-max-2026-06-08": (1_000_000, 65_536),
            "kimi-k2.7-code": (262_144, 32_768),
            "glm-5.2": (1_000_000, 131_072),
            "qwen3.8-max-preview": (1_000_000, 131_072),
        }
        for model_name, (context_window, max_output) in cases.items():
            with self.subTest(model_name=model_name):
                result = _model_discovery_item(
                    {"model_name": model_name, "metadata": {}}, None, "供应商接口"
                )
                self.assertEqual(result.context_window_tokens, context_window)
                self.assertEqual(result.max_output_tokens, max_output)
                self.assertEqual(
                    result.context_compaction_threshold_tokens,
                    context_window - max_output,
                )
                self.assertEqual(result.context_window_source, "内置预设")

    def test_discovery_backfills_only_legacy_default_model_budgets(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        try:
            model = AIModel(provider_id=7, model_name="deepseek-v4-pro", display_name="DeepSeek V4 Pro")
            db.add(model)
            db.commit()
            capability = _model_discovery_item(
                {"model_name": "deepseek-v4-pro", "metadata": {}}, None, "供应商接口"
            )

            self.assertEqual(_sync_default_discovered_budgets(db, 7, [capability]), 1)
            self.assertEqual(model.context_window_tokens, 1_000_000)

            model.context_compaction_threshold_tokens = 900_000
            db.commit()
            self.assertEqual(_sync_default_discovered_budgets(db, 7, [capability]), 0)
            self.assertEqual(model.context_compaction_threshold_tokens, 900_000)
        finally:
            db.close()
            engine.dispose()

    def test_discovery_replaces_only_legacy_proportional_preview_budget(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        try:
            capability = _model_discovery_item(
                {"model_name": "deepseek-v4-pro", "metadata": {}}, None, "供应商接口"
            )
            model = AIModel(
                provider_id=8,
                model_name="deepseek-v4-pro",
                display_name="DeepSeek V4 Pro",
                context_window_tokens=capability.context_window_tokens,
                context_compaction_threshold_tokens=capability.context_compaction_threshold_tokens,
                max_output_tokens=capability.max_output_tokens,
                tool_result_max_tokens=capability.context_compaction_threshold_tokens // 16,
            )
            db.add(model)
            db.commit()

            self.assertEqual(_sync_default_discovered_budgets(db, 8, [capability]), 1)
            self.assertEqual(model.tool_result_max_tokens, 16_384)
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
