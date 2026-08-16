from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessageChunk, HumanMessage

from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.services import chat_agent
from app.services.ai_client.openai_responses import OpenAIResponsesClient


class OpenAIResponsesClientTests(unittest.TestCase):
    def test_payload_translates_messages_and_tools(self) -> None:
        payload = OpenAIResponsesClient._build_payload(
            "gpt-5",
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "look up",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            123,
            False,
            reasoning_effort="medium",
        )

        self.assertEqual(payload["max_output_tokens"], 123)
        self.assertEqual(payload["reasoning"], {"effort": "medium"})
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(payload["tools"][0]["name"], "lookup")
        self.assertEqual(payload["input"][2]["type"], "function_call")
        self.assertEqual(payload["input"][3], {"type": "function_call_output", "call_id": "call_1", "output": "result"})

    def test_payload_drops_unsupported_prompt_cache_breakpoint(self) -> None:
        payload = OpenAIResponsesClient._build_payload(
            "gpt-5.6",
            [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": "stable rules",
                            "prompt_cache_breakpoint": {"mode": "explicit"},
                        },
                        {"type": "text", "text": "dynamic document"},
                    ],
                }
            ],
            None,
            64,
            False,
            prompt_cache_key="yb-agent-v1-p4-m8-s0",
        )

        self.assertEqual(payload["prompt_cache_key"], "yb-agent-v1-p4-m8-s0")
        self.assertNotIn("prompt_cache_options", payload)
        self.assertNotIn("prompt_cache_breakpoint", payload["input"][0]["content"][0])

    def test_chat_and_stream_parse_responses_events(self) -> None:
        requests: list[httpx.Request] = []

        stream_events = [
            {"type": "response.output_text.delta", "delta": "pong"},
            {
                "type": "response.reasoning_summary_text.delta",
                "delta": "checked",
            },
            {
                "type": "response.output_item.added",
                "item": {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": ""},
            },
            {"type": "response.function_call_arguments.delta", "item_id": "fc_1", "delta": '{"q":"x"}'},
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": '{"q":"x"}'},
            },
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 4,
                        "input_tokens_details": {"cached_tokens": 2},
                    },
                },
            },
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = json.loads(request.content)
            if body.get("stream"):
                content = "".join(f"data: {json.dumps(item)}\n\n" for item in stream_events)
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content.encode())
            return httpx.Response(
                200,
                json={
                    "id": "resp_1",
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "pong"}]}],
                },
            )

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient

        async def run() -> tuple[str, list[object]]:
            client = OpenAIResponsesClient("https://example.test/v1", "test-key")
            with patch(
                "app.services.ai_client.openai_responses.httpx.AsyncClient",
                side_effect=lambda **kwargs: real_async_client(transport=transport, **kwargs),
            ):
                result = await client.chat("gpt-5", [{"role": "user", "content": "ping"}], max_tokens=8)
                events = [
                    event
                    async for event in client.chat_stream(
                        "gpt-5",
                        [{"role": "user", "content": "ping"}],
                        max_tokens=8,
                    )
                ]
            return result.content, events

        content, events = asyncio.run(run())
        self.assertEqual(content, "pong")
        self.assertEqual([event.type for event in events], ["text_delta", "reasoning_delta", "done"])
        self.assertEqual(events[0].text_delta, "pong")
        self.assertEqual(events[1].reasoning_delta, "checked")
        self.assertEqual(events[-1].tool_calls[0].arguments, {"q": "x"})
        self.assertEqual(events[-1].usage["input_tokens"], 10)
        self.assertEqual(str(requests[0].url), "https://example.test/v1/responses")
        self.assertEqual(requests[0].headers["authorization"], "Bearer test-key")


class OpenAIResponsesAgentTests(unittest.TestCase):
    def test_langchain_model_uses_responses_payload_and_no_stream_options(self) -> None:
        provider = AIProvider(
            provider_type=ProviderType.OPENAI_RESPONSES,
            base_url="https://api.openai.com/v1",
            api_key_encrypted="encrypted",
        )
        model = AIModel(
            provider_id=1,
            model_name="gpt-5",
            display_name="GPT-5",
            max_output_tokens=512,
            thinking_config={"enabled": {"reasoning_effort": "medium"}},
        )
        with patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            chat_model, _ = chat_agent.build_chat_model(provider, model, "enabled", streaming=True)

        self.assertTrue(chat_model.use_responses_api)
        self.assertEqual(chat_model.output_version, "responses/v1")
        self.assertFalse(chat_model.stream_usage)
        payload = chat_model._get_request_payload([HumanMessage(content="hello")])
        self.assertIn("input", payload)
        self.assertNotIn("messages", payload)
        self.assertNotIn("stream_options", payload)
        self.assertEqual(payload["reasoning"], {"effort": "medium"})

    def test_prompt_cache_key_reaches_responses_payload_without_breakpoints(self) -> None:
        provider = AIProvider(
            id=4,
            provider_type=ProviderType.OPENAI_RESPONSES,
            base_url="https://api.openai.com/v1",
            api_key_encrypted="encrypted",
        )
        model = AIModel(
            id=8,
            provider_id=4,
            model_name="gpt-5.6",
            display_name="GPT-5.6",
            max_output_tokens=512,
            prompt_cache_enabled=True,
        )
        with patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            chat_model, _ = chat_agent.build_chat_model(
                provider,
                model,
                "auto",
                prompt_cache_key="yb-agent-v1-p4-m8-s0",
            )

        payload = chat_model._get_request_payload([HumanMessage(content="hello")])
        self.assertEqual(payload["prompt_cache_key"], "yb-agent-v1-p4-m8-s0")
        self.assertNotIn("prompt_cache_options", payload)

        system = chat_agent.build_system_message(chat_model, "标题", "<p>正文</p>")
        system_payload = chat_model._get_request_payload([system])
        self.assertIsInstance(system_payload["input"][0]["content"], str)
        self.assertNotIn("prompt_cache_breakpoint", str(system_payload))

    def test_prompt_cache_key_reaches_chat_completions_without_breakpoints(self) -> None:
        provider = AIProvider(
            id=4,
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            base_url="https://gateway.example.test/v1",
            api_key_encrypted="encrypted",
        )
        model = AIModel(
            id=8,
            provider_id=4,
            model_name="gpt-5.6",
            display_name="GPT-5.6",
            max_output_tokens=512,
            prompt_cache_enabled=True,
        )
        with patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            chat_model, _ = chat_agent.build_chat_model(
                provider,
                model,
                "auto",
                prompt_cache_key="yb-agent-v1-p4-m8-s0",
            )

        payload = chat_model._get_request_payload([HumanMessage(content="hello")])
        self.assertEqual(payload["prompt_cache_key"], "yb-agent-v1-p4-m8-s0")
        self.assertNotIn("prompt_cache_options", payload)
        self.assertIn("messages", payload)

        system = chat_agent.build_system_message(chat_model, "标题", "<p>正文</p>")
        system_payload = chat_model._get_request_payload([system])
        self.assertIsInstance(system_payload["messages"][0]["content"], str)
        self.assertNotIn("prompt_cache_breakpoint", str(system_payload))

    def test_opted_out_model_keeps_the_existing_request_shape(self) -> None:
        provider = AIProvider(
            id=4,
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            base_url="https://gateway.example.test/v1",
            api_key_encrypted="encrypted",
        )
        model = AIModel(
            id=8,
            provider_id=4,
            model_name="gpt-5.6",
            display_name="GPT-5.6",
            max_output_tokens=512,
            prompt_cache_enabled=False,
        )
        with patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            chat_model, _ = chat_agent.build_chat_model(
                provider,
                model,
                "auto",
                prompt_cache_key="yb-agent-v1-p4-m8-s0",
            )

        payload = chat_model._get_request_payload([HumanMessage(content="hello")])
        self.assertNotIn("prompt_cache_key", payload)
        self.assertNotIn("prompt_cache_options", payload)

    def test_reasoning_summary_content_is_forwarded(self) -> None:
        chunk = AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "thinking"}],
                }
            ]
        )
        self.assertEqual(chat_agent._reasoning_content(chunk), "thinking")

    def test_nested_compatible_reasoning_content_is_forwarded(self) -> None:
        chunk = AIMessageChunk(
            content="",
            additional_kwargs={
                "reasoning_content": [
                    {"type": "reasoning", "text": "先读取文档。"},
                    {"type": "reasoning", "content": "再调整标题层级。"},
                ]
            }
        )

        self.assertEqual(chat_agent._reasoning_content(chunk), "先读取文档。再调整标题层级。")


if __name__ == "__main__":
    unittest.main()
