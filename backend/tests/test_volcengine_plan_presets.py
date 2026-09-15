"""火山方舟 Agent Plan / Coding Plan 套餐预设回归测试。"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.api.routes.ai_providers import _fetch_connection_models, discover_preset_models
from app.schemas.ai_provider import ModelBulkCreateItem, PresetDiscoveryRequest
from app.services.model_presets import get_provider_preset


PLAN_PRESETS = {
    "volcengine_ark_agent_plan": {
        "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
        "models": {"ark-code-latest", "doubao-seed-evolving", "kimi-k3"},
    },
    "volcengine_ark_coding_plan": {
        "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "models": {"ark-code-latest", "glm-latest", "kimi-k2.7-code"},
    },
}


class VolcenginePlanPresetTests(unittest.TestCase):
    def test_plan_presets_use_the_documented_responses_gateways(self) -> None:
        for preset_id, expected in PLAN_PRESETS.items():
            with self.subTest(preset_id=preset_id):
                preset = get_provider_preset(preset_id)
                self.assertIsNotNone(preset)
                self.assertEqual(preset["provider_type"], "openai_responses")
                self.assertEqual(preset["base_url"], expected["base_url"])
                self.assertNotEqual(preset["base_url"], "https://ark.cn-beijing.volces.com/api/v3")
                self.assertEqual(
                    preset["model_discovery"],
                    {
                        "adapter": "openai_compatible",
                        "path": "/models",
                        "response_key": "data",
                    },
                )
                model_names = {model["model_name"] for model in preset["models"]}
                self.assertTrue(expected["models"].issubset(model_names))

    def test_plan_model_capabilities_match_the_documented_operational_limits(self) -> None:
        coding = {
            model["model_name"]: model
            for model in get_provider_preset("volcengine_ark_coding_plan")["models"]
        }

        agent_by_name = {
            model["model_name"]: model
            for model in get_provider_preset("volcengine_ark_agent_plan")["models"]
        }
        self.assertEqual(
            (
                agent_by_name["ark-code-latest"]["context_window_tokens"],
                agent_by_name["ark-code-latest"]["max_output_tokens"],
            ),
            (256_000, 32_000),
        )
        self.assertEqual(
            (
                agent_by_name["doubao-seed-evolving"]["context_window_tokens"],
                agent_by_name["doubao-seed-evolving"]["max_output_tokens"],
            ),
            (1_024_000, 65_536),
        )
        self.assertIn("kimi-k3", agent_by_name)
        self.assertTrue(agent_by_name["doubao-seed-evolving"]["is_multimodal"])
        self.assertFalse(coding["glm-5.3"]["supports_disabled_thinking"])
        self.assertEqual(coding["kimi-k2.7-code"]["thinking_config"], {})

    def test_plan_discovery_calls_documented_models_endpoint(self) -> None:
        preset = get_provider_preset("volcengine_ark_coding_plan")
        request = httpx.Request("GET", f"{preset['base_url']}/models")
        response = httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "ark-code-latest"},
                    {"id": "glm-5.3"},
                    {"id": "newly-enabled-model"},
                ],
            },
            request=request,
        )
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with patch("app.api.routes.ai_providers.httpx.AsyncClient", return_value=client_context):
            result = asyncio.run(
                discover_preset_models(
                    "volcengine_ark_coding_plan", PresetDiscoveryRequest(api_key="test-key")
                )
            )

        discovered = {model.model_name: model for model in result.models}
        client.get.assert_awaited_once_with(
            f"{preset['base_url']}/models",
            headers={"Authorization": "Bearer test-key"},
            params={},
        )
        self.assertEqual(result.source, "供应商接口")
        self.assertIsNone(result.warning)
        self.assertIn("newly-enabled-model", discovered)
        self.assertFalse(discovered["glm-5.3"].supports_disabled_thinking)
        self.assertEqual(discovered["ark-code-latest"].context_window_tokens, 256_000)

    def test_plan_model_endpoint_parser_uses_openai_data_items(self) -> None:
        preset = get_provider_preset("volcengine_ark_agent_plan")
        response = httpx.Response(
            200,
            json={"data": [{"id": "ark-code-latest"}, {"id": "ark-code-latest"}, {"id": "kimi-k3"}]},
            request=httpx.Request("GET", f"{preset['base_url']}/models"),
        )
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with patch("app.api.routes.ai_providers.httpx.AsyncClient", return_value=client_context):
            models = asyncio.run(
                _fetch_connection_models("openai_responses", preset["base_url"], "test-key", preset)
            )

        self.assertEqual([model["model_name"] for model in models], ["ark-code-latest", "kimi-k3"])

    def test_all_plan_models_pass_the_persisted_budget_validator(self) -> None:
        for preset_id in PLAN_PRESETS:
            preset = get_provider_preset(preset_id)
            for model in preset["models"]:
                with self.subTest(preset_id=preset_id, model=model["model_name"]):
                    ModelBulkCreateItem(
                        model_name=model["model_name"],
                        display_name=model["display_name"],
                        context_window_tokens=model["context_window_tokens"],
                        context_compaction_threshold_tokens=model[
                            "context_compaction_threshold_tokens"
                        ],
                        max_output_tokens=model["max_output_tokens"],
                        tool_result_max_tokens=model["tool_result_max_tokens"],
                    )


if __name__ == "__main__":
    unittest.main()
