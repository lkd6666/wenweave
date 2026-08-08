from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  确保关系模型已注册
from fastapi import HTTPException

from app.api.routes.ai_providers import create_model, discover_preset_models, install_preset, update_model, update_provider
from app.db.base import Base
from app.models.ai_provider import AIProvider, ProviderType
from app.schemas.ai_provider import ModelCreate, ModelUpdate, PresetDiscoveryRequest, PresetInstallRequest, ProviderUpdate


class ProviderUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        provider = AIProvider(
            name="测试 Provider",
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            base_url="https://example.test/v1",
            api_key_encrypted="",
        )
        self.db.add(provider)
        self.db.commit()
        self.provider_id = provider.id

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_protocol_type_can_be_changed(self) -> None:
        for provider_type in (
            ProviderType.OPENAI_RESPONSES,
            ProviderType.ANTHROPIC,
            ProviderType.OPENAI_COMPATIBLE,
        ):
            result = update_provider(
                self.provider_id,
                ProviderUpdate(provider_type=provider_type),
                self.db,
            )
            self.assertEqual(result.provider_type, provider_type)
            self.assertEqual(self.db.get(AIProvider, self.provider_id).provider_type, provider_type)

    def test_omitting_protocol_type_preserves_existing_value(self) -> None:
        result = update_provider(
            self.provider_id,
            ProviderUpdate(name="更新名称"),
            self.db,
        )
        self.assertEqual(result.provider_type, ProviderType.OPENAI_COMPATIBLE)
        self.assertEqual(result.name, "更新名称")

    def test_preset_install_can_override_protocol(self) -> None:
        result = install_preset(
            "openai_responses",
            PresetInstallRequest(
                api_key="test-key",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                model_names=["gpt-5"],
            ),
            self.db,
        )
        self.assertEqual(result.provider_type, ProviderType.OPENAI_COMPATIBLE)

    def test_preset_discovery_uses_selected_protocol(self) -> None:
        calls: list[str] = []

        async def fake_fetch(provider_type: str, *args: object) -> list[dict[str, object]]:
            calls.append(provider_type)
            return []

        with patch(
            "app.api.routes.ai_providers._fetch_connection_models",
            new=AsyncMock(side_effect=fake_fetch),
        ):
            asyncio.run(
                discover_preset_models(
                    "openai",
                    PresetDiscoveryRequest(
                        api_key="test-key",
                        provider_type=ProviderType.OPENAI_RESPONSES,
                    ),
                )
            )

        self.assertEqual(calls, [ProviderType.OPENAI_RESPONSES.value])

    def test_prompt_cache_flag_round_trips_for_openai_providers(self) -> None:
        model = create_model(
            self.provider_id,
            ModelCreate(
                model_name="gpt-5.6",
                display_name="GPT-5.6",
                prompt_cache_enabled=True,
            ),
            self.db,
        )
        self.assertTrue(model.prompt_cache_enabled)

        updated = update_model(model.id, ModelUpdate(prompt_cache_enabled=False), self.db)
        self.assertFalse(updated.prompt_cache_enabled)

    def test_prompt_cache_flag_rejects_anthropic_provider(self) -> None:
        update_provider(self.provider_id, ProviderUpdate(provider_type=ProviderType.ANTHROPIC), self.db)

        with self.assertRaises(HTTPException) as raised:
            create_model(
                self.provider_id,
                ModelCreate(model_name="claude", display_name="Claude", prompt_cache_enabled=True),
                self.db,
            )

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
