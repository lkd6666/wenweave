"""轮级重试：瞬时供应商断流会重放当前未完成的模型轮。

供应商流不支持从断点继续读取，因此后端与浏览器都必须丢弃本轮尚未完成的输出，
再发起新请求。工具只会在完整模型消息抵达图节点后执行，故该边界不会重复写入。
"""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessageChunk

from app.services import chat_agent
from app.services.chat_agent import (
    ModelStreamCleanupError,
    _is_retryable_provider_error,
    _openai_reasoning_kwargs,
    _stream_model_turn_with_retry,
    build_chat_model,
    thinking_capability_fallback,
)
from app.models.ai_model import AIModel
from app.models.ai_provider import ProviderType


class _Status(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _Response:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class _Wrapped(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.response = _Response(status_code)


class _FakeModel:
    """按脚本依次抛错或产出 chunk，用来驱动重试路径。"""

    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.attempts = 0

    def astream(self, _messages: object) -> object:
        index = self.attempts
        self.attempts += 1
        step = self.script[index] if index < len(self.script) else self.script[-1]

        async def generate():
            if isinstance(step, Exception):
                raise step
            for item in step if isinstance(step, list) else [step]:
                if isinstance(item, Exception):
                    raise item
                yield item

        return generate()


class _ReasoningNoneRejectedModel:
    def bind_tools(self, _tools: object, **_kwargs: object) -> "_ReasoningNoneRejectedModel":
        return self

    def astream(self, _messages: object, **_kwargs: object) -> object:
        async def generate():
            raise RuntimeError(
                "reasoning_effort: unknown variant `none`, expected one of `high`, `low`, `medium`, `max`, `xhigh`"
            )
            yield None  # pragma: no cover - keeps this an async generator.

        return generate()


class _FallbackReasoningModel:
    def bind_tools(self, _tools: object, **_kwargs: object) -> "_FallbackReasoningModel":
        return self

    def astream(self, _messages: object, **_kwargs: object) -> object:
        async def generate():
            yield "fallback-chunk"

        return generate()


class _FalseThinkingRejectedModel(_ReasoningNoneRejectedModel):
    def astream(self, _messages: object, **_kwargs: object) -> object:
        async def generate():
            raise RuntimeError("The value of the enable_thinking parameter is restricted to True.")
            yield None  # pragma: no cover - keeps this an async generator.

        return generate()


class _SessionReleasedNamespace(SimpleNamespace):
    """Raises if a retry factory touches an ORM-like field after release."""

    _released = False
    _released_fields: frozenset[str] = frozenset()

    def __getattribute__(self, name: str) -> object:
        if name not in {"_released", "_released_fields", "__class__"}:
            released = object.__getattribute__(self, "_released")
            fields = object.__getattribute__(self, "_released_fields")
            if released and name in fields:
                raise AssertionError(f"detached ORM attribute accessed: {name}")
        return super().__getattribute__(name)


def _drain(model: _FakeModel, on_retry: object = None) -> tuple[list[object], list[dict]]:
    """Drain the retry stream with the backoff shortened.

    The production delay is seconds; keeping it here would trade six seconds of
    suite time for no extra coverage, since the delay value itself is asserted
    separately from the emitted heartbeat text.
    """
    events: list[dict] = []

    async def run() -> list[object]:
        return [
            chunk
            async for chunk in _stream_model_turn_with_retry(model, [], events.append, on_retry=on_retry)
        ]

    with mock.patch.object(chat_agent, "MODEL_TURN_RETRY_BASE_SECONDS", 0.001):
        with mock.patch.object(chat_agent.asyncio, "sleep", new=AsyncMock()):
            return asyncio.run(run()), events


class RetryClassifierTests(unittest.TestCase):
    def test_qwen_disabled_mode_omits_rejected_false_thinking_flag(self) -> None:
        model = AIModel(provider_id=1, model_name="qwen3.8-max-preview", display_name="Qwen")

        kwargs, status = _openai_reasoning_kwargs(model, "disabled", "auto")

        self.assertEqual(kwargs, {})
        self.assertFalse(status.applied)
        self.assertIn("不支持关闭推理", status.detail)

    def test_qwen_enabled_config_keeps_true_thinking_flag(self) -> None:
        model = AIModel(
            provider_id=1,
            model_name="qwen3.8-max-preview",
            display_name="Qwen",
            thinking_config={"enabled": {"enable_thinking": True}},
        )

        kwargs, status = _openai_reasoning_kwargs(model, "enabled", "auto")

        self.assertEqual(kwargs, {"extra_body": {"enable_thinking": True}})
        self.assertTrue(status.applied)

    def test_disabled_reasoning_effort_retries_with_provider_default_before_output(self) -> None:
        provider = SimpleNamespace(
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key_encrypted="encrypted",
            base_url="https://example.invalid/v1",
        )
        model = AIModel(
            provider_id=1,
            model_name="gpt-5-compatible",
            display_name="GPT compatible",
            max_output_tokens=2048,
        )
        primary = _ReasoningNoneRejectedModel()
        fallback = _FallbackReasoningModel()
        with mock.patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            with mock.patch.object(
                chat_agent,
                "OpenAICompatibleChatModel",
                side_effect=[primary, fallback],
            ) as construct:
                chat_model, _ = build_chat_model(provider, model, "disabled")

                async def collect() -> list[object]:
                    return [chunk async for chunk in chat_model.bind_tools([]).astream([])]

                chunks = asyncio.run(collect())

        self.assertEqual(chunks, ["fallback-chunk"])
        self.assertEqual(construct.call_count, 2)
        self.assertEqual(construct.call_args_list[0].kwargs["reasoning_effort"], "none")
        self.assertNotIn("reasoning_effort", construct.call_args_list[1].kwargs)
        self.assertEqual(thinking_capability_fallback(chat_model), {"reason": "reasoning_effort_none"})

    def test_persisted_disabled_thinking_capability_downgrades_stale_request_to_auto(self) -> None:
        provider = SimpleNamespace(
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key_encrypted="encrypted",
            base_url="https://example.invalid/v1",
        )
        model = AIModel(
            provider_id=1,
            model_name="gpt-5-compatible",
            display_name="GPT compatible",
            max_output_tokens=2048,
            supports_disabled_thinking=False,
            thinking_config={"disabled": {"reasoning_effort": "none"}},
        )
        sentinel = object()
        with mock.patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            with mock.patch.object(chat_agent, "OpenAICompatibleChatModel", return_value=sentinel) as construct:
                built, status = build_chat_model(provider, model, "disabled")

        self.assertIs(built, sentinel)
        self.assertEqual(status.requested, "auto")
        self.assertNotIn("reasoning_effort", construct.call_args.kwargs)

    def test_disabled_enable_thinking_retries_once_and_shares_fallback_state_with_bound_tools(self) -> None:
        provider = SimpleNamespace(
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key_encrypted="encrypted",
            base_url="https://example.invalid/v1",
        )
        model = AIModel(
            provider_id=1,
            model_name="qwen-compatible",
            display_name="Qwen compatible",
            max_output_tokens=2048,
            thinking_config={"disabled": {"enable_thinking": False}},
        )
        primary = _FalseThinkingRejectedModel()
        fallback = _FallbackReasoningModel()
        with mock.patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            with mock.patch.object(
                chat_agent,
                "OpenAICompatibleChatModel",
                side_effect=[primary, fallback],
            ) as construct:
                chat_model, _ = build_chat_model(provider, model, "disabled")

                async def collect() -> list[object]:
                    return [chunk async for chunk in chat_model.bind_tools([]).astream([])]

                chunks = asyncio.run(collect())

        self.assertEqual(chunks, ["fallback-chunk"])
        self.assertEqual(construct.call_count, 2)
        self.assertIn("extra_body", construct.call_args_list[0].kwargs)
        self.assertNotIn("extra_body", construct.call_args_list[1].kwargs)
        self.assertEqual(thinking_capability_fallback(chat_model), {"reason": "enable_thinking_false"})

    def test_disabled_thinking_fallback_does_not_read_released_orm_objects(self) -> None:
        provider = _SessionReleasedNamespace(
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key_encrypted="encrypted",
            base_url="https://example.invalid/v1",
            _released_fields=frozenset({"base_url", "api_key_encrypted"}),
        )
        model = _SessionReleasedNamespace(
            model_name="qwen-compatible",
            max_output_tokens=2048,
            thinking_config={"disabled": {"enable_thinking": False}},
            supports_disabled_thinking=True,
            _released_fields=frozenset({"model_name", "max_output_tokens", "thinking_config"}),
        )
        primary = _FalseThinkingRejectedModel()
        fallback = _FallbackReasoningModel()
        with mock.patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            with mock.patch.object(
                chat_agent,
                "OpenAICompatibleChatModel",
                side_effect=[primary, fallback],
            ) as construct:
                chat_model, _ = build_chat_model(provider, model, "disabled")
                provider._released = True
                model._released = True

                async def collect() -> list[object]:
                    return [chunk async for chunk in chat_model.bind_tools([]).astream([])]

                chunks = asyncio.run(collect())

        self.assertEqual(chunks, ["fallback-chunk"])
        self.assertEqual(construct.call_count, 2)

    def test_qwen_reasoning_none_retries_when_gateway_reports_enable_thinking_constraint(self) -> None:
        provider = SimpleNamespace(
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key_encrypted="encrypted",
            base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
        model = AIModel(
            provider_id=1,
            model_name="qwen3.8-max-preview",
            display_name="Qwen 3.8 Max Preview",
            max_output_tokens=2048,
            thinking_config={"disabled": {"reasoning_effort": "none"}},
        )
        primary = _FalseThinkingRejectedModel()
        fallback = _FallbackReasoningModel()
        with mock.patch.object(chat_agent, "decrypt_secret", return_value="test-key"):
            with mock.patch.object(
                chat_agent,
                "OpenAICompatibleChatModel",
                side_effect=[primary, fallback],
            ) as construct:
                chat_model, _ = build_chat_model(provider, model, "disabled")

                async def collect() -> list[object]:
                    return [chunk async for chunk in chat_model.bind_tools([]).astream([])]

                chunks = asyncio.run(collect())

        self.assertEqual(chunks, ["fallback-chunk"])
        self.assertEqual(construct.call_count, 2)
        self.assertEqual(construct.call_args_list[0].kwargs["reasoning_effort"], "none")
        self.assertNotIn("reasoning_effort", construct.call_args_list[1].kwargs)
        self.assertEqual(thinking_capability_fallback(chat_model), {"reason": "enable_thinking_false"})

    def test_rate_limit_and_server_errors_are_retryable(self) -> None:
        self.assertTrue(_is_retryable_provider_error(_Status("request timeout", 408)))
        self.assertTrue(_is_retryable_provider_error(_Status("rate limited", 429)))
        self.assertTrue(_is_retryable_provider_error(_Status("overloaded", 503)))
        self.assertTrue(_is_retryable_provider_error(_Status("bad gateway", 502)))

    def test_client_errors_other_than_429_are_not_retryable(self) -> None:
        """400/401/404 是请求本身的问题，重试只会烧配额并推迟真正的报错。"""
        for status in (400, 401, 403, 404, 422):
            self.assertFalse(
                _is_retryable_provider_error(_Status("bad request", status)),
                f"status {status} 不应重试",
            )

    def test_status_is_read_from_a_wrapped_response(self) -> None:
        self.assertTrue(_is_retryable_provider_error(_Wrapped("upstream", 500)))
        self.assertFalse(_is_retryable_provider_error(_Wrapped("nope", 401)))

    def test_message_fallback_when_no_status_is_available(self) -> None:
        self.assertTrue(_is_retryable_provider_error(RuntimeError("connection reset by peer")))
        self.assertTrue(_is_retryable_provider_error(RuntimeError("server is overloaded")))
        self.assertFalse(_is_retryable_provider_error(RuntimeError("invalid api key")))

    def test_stream_cleanup_failure_is_not_retryable(self) -> None:
        self.assertFalse(_is_retryable_provider_error(ModelStreamCleanupError("close")))


class RetryStreamTests(unittest.TestCase):
    def test_transient_failure_before_any_output_is_retried(self) -> None:
        model = _FakeModel([_Status("overloaded", 503), "chunk-1"])

        chunks, events = _drain(model)

        self.assertEqual(chunks, ["chunk-1"])
        self.assertEqual(model.attempts, 2)
        self.assertEqual([event["event"] for event in events], ["model_turn_retry"])

    def test_failure_after_output_retries_and_notifies_caller_to_discard_partial_turn(self) -> None:
        """调用方据此撤回 partial output，重放不会向最终时间线重复追加文本。"""
        model = _FakeModel([["chunk-1", _Status("overloaded", 503)], "chunk-2"])
        resets: list[None] = []

        chunks, events = _drain(model, lambda: resets.append(None))

        self.assertEqual(chunks, ["chunk-1", "chunk-2"])
        self.assertEqual(model.attempts, 2)
        self.assertEqual(len(resets), 1)
        self.assertEqual([event["event"] for event in events], ["model_turn_retry"])

    def test_non_retryable_failure_raises_immediately(self) -> None:
        model = _FakeModel([_Status("invalid request", 400), "chunk-1"])

        with self.assertRaises(_Status):
            _drain(model)

        self.assertEqual(model.attempts, 1)

    def test_attempts_are_capped(self) -> None:
        model = _FakeModel([_Status("overloaded", 503)])

        with mock.patch.object(chat_agent, "MODEL_TURN_MAX_ATTEMPTS", 3):
            with self.assertRaises(_Status):
                _drain(model)

        self.assertEqual(model.attempts, 3)

    def test_retry_after_is_exposed_and_capped_by_the_application_policy(self) -> None:
        error = _Wrapped("rate limited", 429)
        error.response = _Response(429, {"retry-after": "60"})
        model = _FakeModel([error, "chunk-1"])

        chunks, events = _drain(model)

        self.assertEqual(chunks, ["chunk-1"])
        self.assertEqual(model.attempts, 2)
        retry = events[0]["data"]
        self.assertEqual(retry["reason"], "upstream_429")
        self.assertEqual(retry["retry_after_seconds"], 60.0)
        self.assertEqual(retry["delay_seconds"], 60.0)
        self.assertEqual(retry["remaining_attempts"], 2)

    def test_successful_first_attempt_makes_no_retry_and_no_heartbeat(self) -> None:
        model = _FakeModel([["a", "b"]])

        chunks, events = _drain(model)

        self.assertEqual(chunks, ["a", "b"])
        self.assertEqual(model.attempts, 1)
        self.assertEqual(events, [])

    def test_tracker_receives_the_merged_terminal_usage_chunk(self) -> None:
        model = _FakeModel(
            [
                [
                    AIMessageChunk(content="正在处理"),
                    AIMessageChunk(
                        content="",
                        usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
                        chunk_position="last",
                    ),
                    AIMessageChunk(content=""),
                ]
            ]
        )

        class Tracker:
            response: object | None = None

            def complete(self, response: object) -> None:
                self.response = response

            def fail(self, _exc: BaseException) -> None:
                self.fail_called = True

        tracker = Tracker()

        async def run() -> None:
            async for _ in _stream_model_turn_with_retry(
                model,
                [],
                lambda _event: None,
                model_call_tracker_factory=lambda: tracker,
            ):
                pass

        asyncio.run(run())
        usage = chat_agent.usage_from_message(tracker.response)
        assert usage is not None
        self.assertEqual(usage.input_tokens, 120)
        self.assertEqual(usage.output_tokens, 30)


if __name__ == "__main__":
    unittest.main()
