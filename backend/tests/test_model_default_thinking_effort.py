from __future__ import annotations

import unittest
from unittest.mock import patch

import app.models  # noqa: F401 - registers every table before create_all.
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from app import bootstrap
from app.api.routes.ai_providers import _validate_default_thinking_effort
from app.db.base import Base
from app.models.ai_model import AIModel
from app.services.chat_agent import (
    _configured_thinking_params,
    _openai_reasoning_kwargs,
    _resolve_default_thinking_effort,
)
from app.services.model_presets import _openai_reasoning_config


class ModelDefaultThinkingEffortTests(unittest.TestCase):
    def test_openai_preset_exposes_max_effort(self) -> None:
        config = _openai_reasoning_config()

        self.assertEqual(config["efforts"]["max"], {"reasoning_effort": "max"})

    def test_concrete_default_requires_a_configured_effort(self) -> None:
        config = {"efforts": {"max": {"reasoning_effort": "max"}}}

        _validate_default_thinking_effort(config, "max")
        with self.assertRaises(HTTPException) as error:
            _validate_default_thinking_effort(config, "high")

        self.assertEqual(error.exception.status_code, 422)

    def test_model_default_overrides_enabled_mapping(self) -> None:
        model = AIModel(
            provider_id=1,
            model_name="gpt-5",
            display_name="GPT-5",
            default_thinking_effort="max",
            thinking_config={
                "enabled": {"reasoning_effort": "medium"},
                "efforts": {
                    "medium": {"reasoning_effort": "medium"},
                    "max": {"reasoning_effort": "max"},
                },
            },
        )

        effort = _resolve_default_thinking_effort(model, "enabled", "auto")

        self.assertEqual(effort, "max")
        self.assertEqual(_configured_thinking_params(model, "enabled", effort), {"reasoning_effort": "max"})
        request_kwargs, _ = _openai_reasoning_kwargs(model, "enabled", effort)
        self.assertEqual(request_kwargs, {"reasoning_effort": "max"})

    def test_auto_default_keeps_legacy_enabled_mapping(self) -> None:
        model = AIModel(
            provider_id=1,
            model_name="gpt-5",
            display_name="GPT-5",
            default_thinking_effort="auto",
            thinking_config={"enabled": {"reasoning_effort": "medium"}},
        )

        effort = _resolve_default_thinking_effort(model, "enabled", "auto")

        self.assertEqual(effort, "auto")
        self.assertEqual(_configured_thinking_params(model, "enabled", effort), {"reasoning_effort": "medium"})
        self.assertEqual(_resolve_default_thinking_effort(model, "auto", "auto"), "auto")
        self.assertEqual(_resolve_default_thinking_effort(model, "disabled", "auto"), "auto")

    def test_legacy_sqlite_schema_gets_auto_default(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE ai_models"))
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
                        "INSERT INTO ai_models (id, provider_id, model_name, display_name, is_default) "
                        "VALUES (1, 1, 'legacy', 'Legacy', 0)"
                    )
                )

            with patch.object(bootstrap, "engine", engine):
                bootstrap.migrate_schema()

            columns = {column["name"] for column in inspect(engine).get_columns("ai_models")}
            self.assertIn("default_thinking_effort", columns)
            with engine.connect() as connection:
                value = connection.execute(
                    text("SELECT default_thinking_effort FROM ai_models WHERE id = 1")
                ).scalar_one()
            self.assertEqual(value, "auto")
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
