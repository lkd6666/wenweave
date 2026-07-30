"""套餐端点没有 /v1/models 时，模型发现必须给出可理解的提示。

改动前的行为：预设 models 为空时，回退提示是「请检查 API Key 后重试」——把
「该端点根本没有列表接口」这个配置事实误报成密钥错误。这里锁定新行为。
"""
from __future__ import annotations

import asyncio
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.ai_providers import (
    ModelDiscoveryUnsupported,
    _fetch_connection_models,
    discover_preset_models,
    install_preset,
)
from app.db.base import Base
from app.schemas.ai_provider import (
    ModelPresetRead,
    PresetDiscoveryRequest,
    PresetInstallRequest,
)
from app.services.model_presets import (
    AUTH_STYLE_BEARER,
    get_provider_preset,
    resolve_auth_style,
)


class CodingPlanDiscoveryTests(unittest.TestCase):
    def test_unsupported_discovery_raises_before_any_network_call(self) -> None:
        preset = get_provider_preset("aliyun_bailian_coding_plan")
        # 若实现改成真的发请求，这里会因为 DNS/网络而抛别的异常或超时。
        with self.assertRaises(ModelDiscoveryUnsupported):
            asyncio.run(
                _fetch_connection_models("anthropic", preset["base_url"], "test-key", preset)
            )

    def test_preset_discovery_returns_builtin_models_without_blaming_the_api_key(self) -> None:
        result = asyncio.run(
            discover_preset_models(
                "aliyun_bailian_coding_plan", PresetDiscoveryRequest(api_key="test-key")
            )
        )

        self.assertTrue(result.models, "应回退展示内置模型")
        self.assertIsNotNone(result.warning)
        self.assertNotIn("检查 API Key", result.warning)
        self.assertIn("/v1/messages", result.warning)

    def test_fallback_models_keep_their_declared_long_context(self) -> None:
        result = asyncio.run(
            discover_preset_models(
                "aliyun_bailian_coding_plan", PresetDiscoveryRequest(api_key="test-key")
            )
        )

        by_name = {model.model_name: model for model in result.models}
        self.assertIn("qwen3.7-plus[1m]", by_name)
        self.assertEqual(by_name["qwen3.7-plus[1m]"].context_window_tokens, 1_000_000)
        self.assertEqual(by_name["qwen3.7-plus[1m]"].context_window_source, "内置预设")

    def test_presets_without_unsupported_marker_still_attempt_discovery(self) -> None:
        """回归：只有显式标记的预设才跳过请求，其余预设行为不变。"""
        preset = get_provider_preset("deepseek_anthropic")
        self.assertNotEqual(
            (preset.get("model_discovery") or {}).get("adapter"), "unsupported"
        )

    def test_install_persists_long_context_budget_end_to_end(self) -> None:
        """走完「发现 → 安装」的真实路径，确认落库的是 1M 而不是 32768。

        预设里的容量写对了，也可能在安装阶段被 model_capabilities 覆盖或被预算校验
        拒绝。这里连起来验一遍，避免只在预设层面自证。
        """
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        try:
            discovery = asyncio.run(
                discover_preset_models(
                    "moonshot_anthropic", PresetDiscoveryRequest(api_key="test-key")
                )
            )
            model_names = [model.model_name for model in discovery.models]
            provider = install_preset(
                "moonshot_anthropic",
                PresetInstallRequest(
                    api_key="test-key",
                    model_names=model_names,
                    model_capabilities=[
                        ModelPresetRead(**model.model_dump(exclude={"source", "context_window_source"}))
                        for model in discovery.models
                    ],
                    set_as_default=True,
                ),
                db,
            )

            self.assertEqual(provider.provider_type.value, "anthropic")
            self.assertEqual(provider.base_url, "https://api.moonshot.cn/anthropic")
            persisted = {model.model_name: model for model in provider.models}
            self.assertEqual(persisted["kimi-k3[1m]"].context_window_tokens, 1_000_000)
            self.assertEqual(persisted["kimi-k2.7-code"].context_window_tokens, 262_144)
            # 安装后仅凭 base_url 就要能还原出 Bearer，否则首次对话直接 401。
            self.assertEqual(
                resolve_auth_style(provider.base_url, "anthropic"), AUTH_STYLE_BEARER
            )
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
