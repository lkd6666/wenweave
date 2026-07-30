from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.api.routes.ai_providers import _effective_thinking_config, _model_discovery_item
from app.bootstrap import backfill_official_deepseek_thinking_models


class DisabledThinkingCapabilityTests(unittest.TestCase):
    def test_official_deepseek_discovery_gets_native_toggle_mapping(self) -> None:
        item = _model_discovery_item(
            {"model_name": "deepseek-chat", "metadata": {}},
            {"base_url": "https://api.deepseek.com/v1", "models": []},
            "供应商接口",
        )

        self.assertEqual(item.thinking_config["disabled"], {"thinking": {"type": "disabled"}})
        self.assertTrue(item.supports_disabled_thinking)

    def test_official_deepseek_default_does_not_replace_custom_mapping(self) -> None:
        custom = {"disabled": {"reasoning_effort": "none"}}

        self.assertEqual(
            _effective_thinking_config("https://api.deepseek.com/v1/", {}),
            {
                "enabled": {"thinking": {"type": "enabled"}},
                "disabled": {"thinking": {"type": "disabled"}},
            },
        )
        self.assertIs(_effective_thinking_config("https://api.deepseek.com/v1", custom), custom)

    def test_startup_backfill_only_changes_empty_official_deepseek_mappings(self) -> None:
        empty = SimpleNamespace(thinking_config={}, supports_disabled_thinking=False)
        custom = SimpleNamespace(thinking_config={"enabled": {"custom": True}}, supports_disabled_thinking=True)
        provider = SimpleNamespace(base_url="https://api.deepseek.com/v1", models=[empty, custom])
        db = Mock()
        db.query.return_value.all.return_value = [provider]

        changed = backfill_official_deepseek_thinking_models(db)

        self.assertEqual(changed, 2)
        self.assertEqual(empty.thinking_config["disabled"], {"thinking": {"type": "disabled"}})
        self.assertEqual(custom.thinking_config, {"enabled": {"custom": True}})
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
