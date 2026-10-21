from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  确保关系模型已注册
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.ai_providers import (
    create_image_model,
    create_model,
    discover_preset_models,
    install_preset,
    update_image_model,
    update_model,
    update_provider,
)
from app.bootstrap import migrate_anthropic_thinking_models, migrate_schema
from app.api.routes.models import list_image_models, list_models
from app.db.base import Base
from app.core.token_budgets import DEFAULT_TOOL_RESULT_MAX_TOKENS
from app.models.ai_image_model import AIImageModel
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.user import UserRole
from app.schemas.ai_provider import (
    ImageModelCreate,
    ImageModelUpdate,
    ModelCreate,
    ModelRead,
    ModelUpdate,
    PresetDiscoveryRequest,
    PresetInstallRequest,
    ProviderUpdate,
)
from app.services.model_access import (
    can_access_image_model,
    can_access_model,
    is_available_in_time_ranges,
)


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

    def test_schema_migration_upgrades_only_the_legacy_preview_default(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        try:
            provider = AIProvider(
                name="迁移测试",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                base_url="https://example.test/v1",
                api_key_encrypted="",
            )
            db.add(provider)
            db.flush()
            legacy = AIModel(
                provider_id=provider.id,
                model_name="legacy-default",
                display_name="Legacy default",
                context_window_tokens=32_768,
                context_compaction_threshold_tokens=24_576,
                max_output_tokens=8_192,
                tool_result_max_tokens=8_192,
            )
            customized = AIModel(
                provider_id=provider.id,
                model_name="custom-preview",
                display_name="Custom preview",
                context_window_tokens=128_000,
                context_compaction_threshold_tokens=119_808,
                max_output_tokens=8_192,
                tool_result_max_tokens=8_192,
            )
            db.add_all((legacy, customized))
            db.commit()
            legacy_id, customized_id = legacy.id, customized.id
        finally:
            db.close()

        try:
            with patch("app.bootstrap.engine", engine):
                migrate_schema()
            with Session(engine) as verify_db:
                self.assertEqual(
                    verify_db.get(AIModel, legacy_id).tool_result_max_tokens,
                    DEFAULT_TOOL_RESULT_MAX_TOKENS,
                )
                self.assertEqual(verify_db.get(AIModel, customized_id).tool_result_max_tokens, 8_192)
        finally:
            engine.dispose()

    def test_prompt_cache_flag_round_trips_for_anthropic_provider(self) -> None:
        update_provider(self.provider_id, ProviderUpdate(provider_type=ProviderType.ANTHROPIC), self.db)
        model = create_model(
            self.provider_id,
            ModelCreate(model_name="claude", display_name="Claude", prompt_cache_enabled=True),
            self.db,
        )
        self.assertTrue(model.prompt_cache_enabled)
        updated = update_model(model.id, ModelUpdate(prompt_cache_enabled=False), self.db)
        self.assertFalse(updated.prompt_cache_enabled)

    def test_anthropic_model_normalizes_openai_thinking_mapping(self) -> None:
        update_provider(self.provider_id, ProviderUpdate(provider_type=ProviderType.ANTHROPIC), self.db)

        model = create_model(
            self.provider_id,
            ModelCreate(
                model_name="claude-opus-5",
                display_name="Claude Opus 5",
                thinking_config={
                    "enabled": {"reasoning_effort": "medium"},
                    "efforts": {"xhigh": {"reasoning_effort": "xhigh"}},
                },
            ),
            self.db,
        )

        self.assertEqual(model.thinking_config["enabled"], {"thinking": {"type": "adaptive"}, "effort": "medium"})
        self.assertEqual(model.thinking_config["efforts"]["xhigh"], {"thinking": {"type": "adaptive"}, "effort": "xhigh"})

    def test_startup_migrates_existing_anthropic_openai_mapping(self) -> None:
        update_provider(self.provider_id, ProviderUpdate(provider_type=ProviderType.ANTHROPIC), self.db)
        model = create_model(
            self.provider_id,
            ModelCreate(model_name="claude", display_name="Claude"),
            self.db,
        )
        model.thinking_config = {
            "enabled": {"reasoning_effort": "medium"},
            "efforts": {"high": {"reasoning_effort": "high"}},
        }
        self.db.commit()

        changed = migrate_anthropic_thinking_models(self.db)

        self.assertEqual(changed, 1)
        self.assertEqual(model.thinking_config["enabled"], {"thinking": {"type": "adaptive"}, "effort": "medium"})
        self.assertEqual(model.thinking_config["efforts"]["high"], {"thinking": {"type": "adaptive"}, "effort": "high"})

    def test_model_list_includes_provider_name(self) -> None:
        create_model(
            self.provider_id,
            ModelCreate(model_name="gpt-5.6", display_name="GPT-5.6"),
            self.db,
        )

        models = list_models(SimpleNamespace(role=UserRole.ADMIN), self.db)
        payload = ModelRead.model_validate(models[0])

        self.assertEqual(payload.provider_name, "测试 Provider")

    def test_enablement_round_trips_and_filters_models(self) -> None:
        text_model = create_model(
            self.provider_id,
            ModelCreate(model_name="enabled-chat", display_name="Enabled Chat"),
            self.db,
        )
        provider = self.db.get(AIProvider, self.provider_id)
        assert provider is not None
        provider.image_protocol = "openai_images"
        provider.image_base_url = "https://example.test/v1"
        self.db.commit()
        image_model = create_image_model(
            self.provider_id,
            ImageModelCreate(model_name="enabled-image", display_name="Enabled Image"),
            self.db,
        )
        admin = SimpleNamespace(role=UserRole.ADMIN)

        self.assertTrue(text_model.is_enabled)
        self.assertTrue(image_model.is_enabled)
        self.assertTrue(can_access_model(admin, text_model))
        self.assertTrue(can_access_image_model(admin, image_model))

        update_model(text_model.id, ModelUpdate(is_enabled=False), self.db)
        update_image_model(image_model.id, ImageModelUpdate(is_enabled=False), self.db)
        self.assertFalse(can_access_model(admin, text_model))
        self.assertFalse(can_access_image_model(admin, image_model))
        self.assertEqual(list_models(admin, self.db), [])
        self.assertEqual(list_image_models(admin, self.db), [])

        update_model(text_model.id, ModelUpdate(is_enabled=True), self.db)
        update_image_model(image_model.id, ImageModelUpdate(is_enabled=True), self.db)
        update_provider(self.provider_id, ProviderUpdate(is_enabled=False), self.db)
        self.assertFalse(can_access_model(admin, text_model))
        self.assertFalse(can_access_image_model(admin, image_model))
        self.assertEqual(list_models(admin, self.db), [])
        self.assertEqual(list_image_models(admin, self.db), [])

        updated_provider = update_provider(self.provider_id, ProviderUpdate(is_enabled=True), self.db)
        self.assertTrue(updated_provider.is_enabled)
        self.assertTrue(can_access_model(admin, text_model))
        self.assertTrue(can_access_image_model(admin, image_model))
        self.assertEqual([model.id for model in list_models(admin, self.db)], [text_model.id])
        self.assertEqual([model.id for model in list_image_models(admin, self.db)], [image_model.id])

    def test_availability_time_ranges_round_trip_and_require_provider_intersection(self) -> None:
        provider = self.db.get(AIProvider, self.provider_id)
        assert provider is not None
        provider.availability_time_ranges = [{"start": "09:00", "end": "18:00"}]
        self.db.commit()
        model = create_model(
            self.provider_id,
            ModelCreate(
                model_name="scheduled-chat",
                display_name="Scheduled Chat",
                availability_time_ranges=[{"start": "10:00", "end": "12:00"}],
            ),
            self.db,
        )
        admin = SimpleNamespace(role=UserRole.ADMIN)
        available_at = datetime(2026, 8, 13, 2, 0, tzinfo=timezone.utc)  # 10:00 CST
        unavailable_at = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)  # 12:00 CST

        self.assertEqual(model.availability_time_ranges, [{"start": "10:00", "end": "12:00"}])
        self.assertTrue(can_access_model(admin, model, now=available_at))
        self.assertFalse(can_access_model(admin, model, now=unavailable_at))

        provider.availability_time_ranges = [{"start": "11:00", "end": "18:00"}]
        self.db.commit()
        self.assertFalse(can_access_model(admin, model, now=available_at))
        self.assertTrue(can_access_model(admin, model, now=datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)))

        result = update_model(
            model.id,
            ModelUpdate(availability_time_ranges=[{"start": "13:00", "end": "14:00"}]),
            self.db,
        )
        self.assertEqual(result.availability_time_ranges, [{"start": "13:00", "end": "14:00"}])

    def test_image_model_availability_time_ranges_round_trip(self) -> None:
        provider = self.db.get(AIProvider, self.provider_id)
        assert provider is not None
        provider.image_protocol = "openai_images"
        provider.image_base_url = "https://example.test/v1"
        self.db.commit()
        model = create_image_model(
            self.provider_id,
            ImageModelCreate(
                model_name="scheduled-image",
                display_name="Scheduled Image",
                availability_time_ranges=[{"start": "22:00", "end": "02:00"}],
            ),
            self.db,
        )
        admin = SimpleNamespace(role=UserRole.ADMIN)
        self.assertTrue(can_access_image_model(admin, model, now=datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)))
        self.assertFalse(can_access_image_model(admin, model, now=datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)))

        result = update_image_model(
            model.id,
            ImageModelUpdate(availability_time_ranges=[]),
            self.db,
        )
        self.assertEqual(result.availability_time_ranges, [])
        self.assertTrue(can_access_image_model(admin, model, now=datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)))

    def test_daily_availability_supports_multiple_ranges_boundaries_and_overnight(self) -> None:
        ranges = [
            {"start": "09:00", "end": "12:00"},
            {"start": "22:00", "end": "02:00"},
        ]

        def at(hour: int, minute: int = 0) -> datetime:
            return datetime(2026, 8, 13, hour, minute, tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)

        self.assertTrue(is_available_in_time_ranges([], now=at(6)))
        self.assertTrue(is_available_in_time_ranges(ranges, now=at(9)))
        self.assertFalse(is_available_in_time_ranges(ranges, now=at(12)))
        self.assertTrue(is_available_in_time_ranges(ranges, now=at(22)))
        self.assertTrue(is_available_in_time_ranges(ranges, now=at(1)))
        self.assertFalse(is_available_in_time_ranges(ranges, now=at(2)))

    def test_availability_time_ranges_reject_invalid_and_overlapping_intervals(self) -> None:
        for ranges in (
            [{"start": "09:00", "end": "09:00"}],
            [{"start": "9:00", "end": "10:00"}],
            [{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}],
            [{"start": "22:00", "end": "02:00"}, {"start": "01:00", "end": "03:00"}],
        ):
            with self.assertRaises(ValidationError):
                ModelCreate(model_name="invalid", display_name="Invalid", availability_time_ranges=ranges)

    def test_migration_enables_existing_provider_and_models(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE ai_image_models"))
                connection.execute(text("DROP TABLE ai_models"))
                connection.execute(text("DROP TABLE ai_providers"))
                connection.execute(
                    text(
                        "CREATE TABLE ai_providers ("
                        "id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, "
                        "provider_type VARCHAR(32) NOT NULL, base_url VARCHAR(512) NOT NULL, "
                        "api_key_encrypted TEXT NOT NULL)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE ai_models ("
                        "id INTEGER PRIMARY KEY, provider_id INTEGER NOT NULL, "
                        "model_name VARCHAR(256) NOT NULL, display_name VARCHAR(256) NOT NULL, "
                        "is_default BOOLEAN NOT NULL)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE ai_image_models ("
                        "id INTEGER PRIMARY KEY, provider_id INTEGER NOT NULL, "
                        "model_name VARCHAR(256) NOT NULL, display_name VARCHAR(256) NOT NULL, "
                        "is_default BOOLEAN NOT NULL)"
                    )
                )
                connection.execute(text("INSERT INTO ai_providers VALUES (1, 'Legacy', 'OPENAI_COMPATIBLE', 'https://example.test/v1', '')"))
                connection.execute(text("INSERT INTO ai_models VALUES (1, 1, 'legacy-chat', 'Legacy Chat', 1)"))
                connection.execute(text("INSERT INTO ai_image_models VALUES (1, 1, 'legacy-image', 'Legacy Image', 1)"))

            with patch("app.bootstrap.engine", engine):
                migrate_schema()

            for table_name in ("ai_providers", "ai_models", "ai_image_models"):
                columns = {column["name"] for column in inspect(engine).get_columns(table_name)}
                self.assertIn("is_enabled", columns)
                self.assertIn("availability_time_ranges", columns)
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.execute(text(f"SELECT is_enabled FROM {table_name} WHERE id = 1")).scalar_one(),
                        1,
                    )
                    schedule = connection.execute(
                        text(f"SELECT availability_time_ranges FROM {table_name} WHERE id = 1")
                    ).scalar_one()
                    self.assertEqual(json.loads(schedule) if isinstance(schedule, str) else schedule, [])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
