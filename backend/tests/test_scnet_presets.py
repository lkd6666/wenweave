"""国家超算互联网（SCNet）供应商预设回归测试。"""
from __future__ import annotations

import unittest

from app.services.model_presets import find_provider_preset, get_provider_preset


SCNET_MODELS = {
    "GLM-5.2",
    "GLM-5",
    "GLM-5.1",
    "Kimi-K3",
    "Kimi-K2.7-Code",
    "Kimi-K2.6",
    "Kimi-K2.5",
    "DeepSeek-V4-Flash",
    "DeepSeek-V3.2",
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.5",
    "MiMo-V2.5-Pro",
}

SCNET_CODING_MODELS = {"MiniMax-M2.5", "Qwen3-235B-A22B"}


class ScnetPresetTests(unittest.TestCase):
    def test_regular_and_token_plan_presets_use_official_gateway(self) -> None:
        regular = get_provider_preset("scnet")
        token_plan = get_provider_preset("scnet_token_plan")
        self.assertIsNotNone(regular)
        self.assertIsNotNone(token_plan)
        assert regular is not None
        assert token_plan is not None

        self.assertEqual(regular["provider_type"], "openai_compatible")
        self.assertEqual(token_plan["provider_type"], "openai_responses")
        self.assertEqual(regular["base_url"], "https://api.scnet.cn/api/llm/v1")
        self.assertEqual(token_plan["base_url"], regular["base_url"])
        self.assertEqual(token_plan["api_key_hint"], "sk-tp-...（Token Plan 专属）")

    def test_both_presets_include_the_documented_token_plan_model_catalogue(self) -> None:
        for preset_id in ("scnet", "scnet_token_plan"):
            with self.subTest(preset_id=preset_id):
                preset = get_provider_preset(preset_id)
                assert preset is not None
                self.assertEqual(
                    {model["model_name"] for model in preset["models"]},
                    SCNET_MODELS,
                )
                models = {model["model_name"]: model for model in preset["models"]}
                self.assertTrue(models["Kimi-K2.6"]["is_multimodal"])
                self.assertTrue(models["Kimi-K2.5"]["is_multimodal"])
                self.assertFalse(models["Kimi-K3"]["is_multimodal"])
                self.assertEqual(
                    models["DeepSeek-V4-Flash"]["thinking_config"]["efforts"],
                    {
                        "high": {"reasoning_effort": "high"},
                        "max": {"reasoning_effort": "max"},
                    },
                )
                self.assertEqual(
                    models["DeepSeek-V4-Flash"]["thinking_config"]["disabled"],
                    {"enable_thinking": False},
                )

    def test_model_discovery_uses_openai_models_endpoint(self) -> None:
        for preset_id in ("scnet", "scnet_token_plan", "scnet_coding_plan"):
            with self.subTest(preset_id=preset_id):
                preset = get_provider_preset(preset_id)
                assert preset is not None
                self.assertEqual(
                    preset["model_discovery"],
                    {
                        "adapter": "openai_compatible",
                        "path": "/models",
                        "response_key": "data",
                    },
                )

    def test_coding_plan_uses_its_separate_key_and_model_catalogue(self) -> None:
        preset = get_provider_preset("scnet_coding_plan")
        self.assertIsNotNone(preset)
        assert preset is not None
        self.assertEqual(preset["provider_type"], "openai_responses")
        self.assertEqual(preset["base_url"], "https://api.scnet.cn/api/llm/v1")
        self.assertEqual(preset["api_key_hint"], "sk-sp-...（Coding Plan 专属）")
        self.assertEqual(
            {model["model_name"] for model in preset["models"]},
            SCNET_CODING_MODELS,
        )
        models = {model["model_name"]: model for model in preset["models"]}
        self.assertEqual(
            models["Qwen3-235B-A22B"]["thinking_config"],
            {"enabled": {"enable_thinking": True}, "disabled": {"enable_thinking": False}},
        )

    def test_shared_gateway_fallback_is_selected_by_key_prefix(self) -> None:
        self.assertEqual(
            find_provider_preset(
                "https://api.scnet.cn/api/llm/v1",
                "openai_responses",
                "sk-tp-example",
            )["id"],
            "scnet_token_plan",
        )
        self.assertEqual(
            find_provider_preset(
                "https://api.scnet.cn/api/llm/v1",
                "openai_responses",
                "sk-sp-example",
            )["id"],
            "scnet_coding_plan",
        )
        self.assertEqual(
            find_provider_preset(
                "https://api.scnet.cn/api/llm/v1",
                "openai_compatible",
                "sk-sp-example",
            )["id"],
            "scnet_coding_plan",
        )


if __name__ == "__main__":
    unittest.main()
