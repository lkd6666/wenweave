from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.services import chat_agent
from app.services.ai_client.gemini_native import GeminiNativeClient, messages_to_gemini
from app.services.gemini_native_chat_model import GeminiNativeChatModel
from app.services.model_presets import get_provider_preset


class GeminiNativeTests(unittest.TestCase):
    def test_preset_uses_native_protocol_and_model_specific_thinking_shapes(self) -> None:
        preset = get_provider_preset("gemini")
        self.assertIsNotNone(preset)
        assert preset is not None
        self.assertEqual(preset["provider_type"], "gemini_native")
        self.assertEqual(preset["base_url"], "https://generativelanguage.googleapis.com/v1beta")
        models = {item["model_name"]: item for item in preset["models"]}
        self.assertIn("thinkingBudget", models["gemini-2.5-flash"]["thinking_config"]["enabled"]["thinkingConfig"])
        self.assertIn("thinkingLevel", models["gemini-3-flash-preview"]["thinking_config"]["enabled"]["thinkingConfig"])
        self.assertFalse(models["gemini-3-flash-preview"]["supports_disabled_thinking"])

    def test_native_payload_translates_tools_and_tool_results(self) -> None:
        system, contents = messages_to_gemini(
            [
                {"role": "system", "content": "system"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call-1", "function": {"name": "lookup", "arguments": '{"q":"x"}'}}],
                },
                {"role": "tool", "name": "lookup", "tool_call_id": "call-1", "content": '{"ok":true}'},
            ]
        )
        self.assertEqual(system, {"parts": [{"text": "system"}]})
        self.assertEqual(contents[0]["role"], "model")
        self.assertEqual(contents[0]["parts"][0]["functionCall"]["args"], {"q": "x"})
        self.assertEqual(contents[1]["parts"][0]["functionResponse"]["id"], "call-1")
        client = GeminiNativeClient("https://example.test/v1beta", "key")
        payload = client._build_payload("gemini-2.5-flash", [], [{"function": {"name": "lookup"}}], 100, False)
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 100)
        self.assertEqual(payload["tools"][0]["functionDeclarations"][0]["name"], "lookup")

    def test_langchain_model_exposes_thoughts_tools_and_usage(self) -> None:
        model = GeminiNativeChatModel(model="gemini-3-flash-preview", api_key="key")
        result = model._result(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"thought": True, "text": "checked"},
                                {"text": "done"},
                                {"functionCall": {"name": "lookup", "id": "c1", "args": {"q": "x"}}, "thoughtSignature": "sig"},
                            ]
                        }
                    }
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 8, "totalTokenCount": 18, "thoughtsTokenCount": 3},
            }
        )
        message = result.generations[0].message
        self.assertEqual(message.content, "done")
        self.assertEqual(message.additional_kwargs["thinking"], "checked")
        self.assertEqual(message.tool_calls[0]["name"], "lookup")
        self.assertEqual(message.usage_metadata["output_token_details"]["reasoning"], 3)

    def test_factory_maps_native_thinking_config(self) -> None:
        provider = AIProvider(
            provider_type=ProviderType.GEMINI_NATIVE,
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key_encrypted="encrypted",
        )
        model = AIModel(
            provider_id=1,
            model_name="gemini-2.5-flash",
            display_name="Gemini",
            max_output_tokens=512,
            thinking_config={
                "enabled": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": 1024}},
            },
        )
        with patch.object(chat_agent, "decrypt_secret", return_value="key"):
            chat_model, status = chat_agent.build_chat_model(provider, model, "enabled")
        self.assertIsInstance(chat_model, GeminiNativeChatModel)
        self.assertTrue(status.applied)
        self.assertEqual(chat_model.generation_config["thinkingConfig"]["thinkingBudget"], 1024)

    def test_startup_migration_only_changes_bundled_google_endpoint(self) -> None:
        from app.bootstrap import migrate_gemini_native_providers

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            migrated = AIProvider(
                name="Google",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                api_key_encrypted="",
            )
            custom = AIProvider(
                name="Custom",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                base_url="https://gateway.example/v1beta/openai",
                api_key_encrypted="",
            )
            db.add_all([migrated, custom])
            db.flush()
            db.add(AIModel(provider_id=migrated.id, model_name="gemini-2.5-flash", display_name="Gemini"))
            db.commit()
            self.assertEqual(migrate_gemini_native_providers(db), 2)
            self.assertEqual(migrated.provider_type, ProviderType.GEMINI_NATIVE)
            self.assertEqual(migrated.base_url, "https://generativelanguage.googleapis.com/v1beta")
            self.assertEqual(custom.provider_type, ProviderType.OPENAI_COMPATIBLE)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
