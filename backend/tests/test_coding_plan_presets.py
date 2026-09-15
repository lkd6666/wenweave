"""国内云厂商 Anthropic 兼容套餐（Token Plan / Coding Plan）预设的回归测试。

重点不在于「预设存在」，而在于三个容易静默出错的地方：
  1. 认证头必须按 auth_style 走 Bearer 或 x-api-key，发错了就是 401；
  2. base_url 拼接后必须落在 {gateway}/v1/messages，多补一个 /v1 就是 404；
  3. 容量不能落回 32768 默认值，否则长上下文套餐被砍掉一个数量级且管理端看不出来。
"""
from __future__ import annotations

import unittest

from app.schemas.ai_provider import ModelBulkCreateItem
from app.services.ai_client.anthropic import AnthropicClient
from app.services.model_presets import (
    AUTH_STYLE_BEARER,
    PROVIDER_PRESETS,
    find_provider_preset,
    get_provider_preset,
    resolve_auth_style,
)

CODING_PRESET_IDS = [
    "aliyun_bailian_coding_plan",
    "aliyun_bailian_token_plan",
    "zhipu_coding_plan",
    "moonshot_anthropic",
    "deepseek_anthropic",
]


class CodingPlanPresetTests(unittest.TestCase):
    def test_all_coding_presets_exist_and_use_anthropic_protocol(self) -> None:
        for preset_id in CODING_PRESET_IDS:
            with self.subTest(preset_id=preset_id):
                preset = get_provider_preset(preset_id)
                self.assertIsNotNone(preset, f"预设 {preset_id} 缺失")
                self.assertEqual(preset["provider_type"], "anthropic")
                self.assertTrue(preset["models"], "套餐端点无模型列表接口，必须内置模型")

    def test_base_urls_do_not_double_up_the_version_segment(self) -> None:
        """客户端会拼 /v1/messages，预设里再带 /v1 就会变成 /v1/v1/messages。"""
        for preset_id in CODING_PRESET_IDS:
            with self.subTest(preset_id=preset_id):
                base_url = get_provider_preset(preset_id)["base_url"]
                self.assertFalse(base_url.rstrip("/").endswith("/v1"), base_url)
                self.assertTrue(base_url.startswith("https://"), base_url)
                built = f"{base_url.rstrip('/')}/v1/messages"
                self.assertNotIn("/v1/v1/", built)

    def test_bearer_presets_send_authorization_not_x_api_key(self) -> None:
        bearer_ids = [pid for pid in CODING_PRESET_IDS if get_provider_preset(pid).get("auth_style") == AUTH_STYLE_BEARER]
        self.assertTrue(bearer_ids, "阿里云/智谱/Kimi 应声明 Bearer 认证")
        for preset_id in bearer_ids:
            with self.subTest(preset_id=preset_id):
                preset = get_provider_preset(preset_id)
                client = AnthropicClient(preset["base_url"], "test-key", auth_style=preset["auth_style"])
                headers = client._headers()
                self.assertEqual(headers.get("Authorization"), "Bearer test-key")
                self.assertNotIn("x-api-key", headers)

    def test_deepseek_keeps_documented_x_api_key_header(self) -> None:
        preset = get_provider_preset("deepseek_anthropic")
        client = AnthropicClient(preset["base_url"], "test-key", auth_style=preset["auth_style"])
        headers = client._headers()
        self.assertEqual(headers.get("x-api-key"), "test-key")
        self.assertNotIn("Authorization", headers)

    def test_official_anthropic_preset_is_unchanged_by_auth_style_support(self) -> None:
        """回归：新增 auth_style 不得影响官方 Anthropic 与未声明该字段的预设。"""
        preset = get_provider_preset("anthropic")
        self.assertIsNone(preset.get("auth_style"))
        client = AnthropicClient(preset["base_url"], "test-key")
        headers = client._headers()
        self.assertEqual(headers.get("x-api-key"), "test-key")
        self.assertNotIn("Authorization", headers)

    def test_auth_style_is_recoverable_from_stored_base_url(self) -> None:
        """安装后数据库只存 base_url，运行时要能据此还原认证方式。"""
        preset = get_provider_preset("zhipu_coding_plan")
        self.assertEqual(resolve_auth_style(preset["base_url"], "anthropic"), AUTH_STYLE_BEARER)
        # create_provider 会 rstrip("/")，带尾斜杠也必须匹配得上
        self.assertEqual(resolve_auth_style(preset["base_url"] + "/", "anthropic"), AUTH_STYLE_BEARER)
        # 官方 Anthropic 与未知地址回落到 x-api-key
        self.assertEqual(resolve_auth_style("https://api.anthropic.com", "anthropic"), "x-api-key")
        self.assertEqual(resolve_auth_style("https://example.invalid", "anthropic"), "x-api-key")

    def test_zhipu_and_deepseek_gateways_are_distinct_from_existing_openai_presets(self) -> None:
        """智谱既有 OpenAI 兼容预设，新增的 Anthropic 端点不能互相顶掉。"""
        openai_preset = find_provider_preset("https://open.bigmodel.cn/api/paas/v4", "openai_compatible")
        anthropic_preset = find_provider_preset("https://open.bigmodel.cn/api/anthropic", "anthropic")
        self.assertEqual(openai_preset["id"], "zhipu")
        self.assertEqual(anthropic_preset["id"], "zhipu_coding_plan")

    def test_long_context_models_do_not_fall_back_to_the_32k_default(self) -> None:
        for preset_id in CODING_PRESET_IDS:
            preset = get_provider_preset(preset_id)
            for model in preset["models"]:
                if not model["model_name"].endswith("[1m]"):
                    continue
                with self.subTest(preset_id=preset_id, model=model["model_name"]):
                    self.assertEqual(model["context_window_tokens"], 1_000_000)

    def test_every_coding_model_satisfies_the_persisted_budget_validator(self) -> None:
        """预算算错会在安装时才 422，这里提前拦住。"""
        for preset_id in CODING_PRESET_IDS:
            preset = get_provider_preset(preset_id)
            for model in preset["models"]:
                with self.subTest(preset_id=preset_id, model=model["model_name"]):
                    item = ModelBulkCreateItem(
                        model_name=model["model_name"],
                        display_name=model["display_name"],
                        context_window_tokens=model["context_window_tokens"],
                        context_compaction_threshold_tokens=model["context_compaction_threshold_tokens"],
                        max_output_tokens=model["max_output_tokens"],
                        tool_result_max_tokens=model["tool_result_max_tokens"],
                    )
                    self.assertLessEqual(
                        item.context_compaction_threshold_tokens + item.max_output_tokens,
                        item.context_window_tokens,
                    )

    def test_preset_ids_are_unique_and_shared_gateways_declare_key_prefixes(self) -> None:
        ids = [preset["id"] for preset in PROVIDER_PRESETS]
        self.assertEqual(len(ids), len(set(ids)))
        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for preset in PROVIDER_PRESETS:
            key = (preset["provider_type"], preset["base_url"].rstrip("/").lower())
            grouped.setdefault(key, []).append(preset)
        for key, presets in grouped.items():
            if len(presets) <= 1:
                continue
            prefixes = [str(preset.get("api_key_prefix") or "") for preset in presets]
            self.assertEqual(len(prefixes), len(set(prefixes)), key)
            self.assertTrue(all(prefixes), key)


if __name__ == "__main__":
    unittest.main()
