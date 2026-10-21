"""run 内上下文压缩：预算、工具配对与不可丢弃部分。

LangGraph 会把每一轮工具结果累积进 state，长任务（历史翻页、多轮图片核验）
会把请求撑到 provider 上限并让整轮失败。compact_run_messages 只裁剪「发出去
的消息」，不动 graph state。最硬的约束是：带 tool_calls 的 AIMessage 与它的
ToolMessage 绝不能被拆开，否则 Anthropic 与 OpenAI 都会直接拒绝请求。
"""
from __future__ import annotations

import json
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.services.chat_agent import (
    RUN_VERBATIM_CYCLE_COUNT,
    _digest_cycle,
    _effective_run_input_budget,
    _message_tokens,
    _provider_message_tokens,
    _should_publish_runtime_compaction,
    _split_run_cycles,
    build_compaction_model,
    compact_run_messages,
    compact_run_messages_with_model,
    RuntimeCompactionError,
    _dynamic_tool_result_limit,
    thinking_capability_fallback_data,
)
from app.services.agent_context import (
    COMPACTION_MODEL_MAX_OUTPUT_TOKENS,
    COMPACTION_MODEL_MAX_RETRIES,
    COMPACTION_MODEL_REQUEST_TIMEOUT_SECONDS,
    compaction_failure_detail,
)
from app.services.token_budget import estimate_tokens


def _cycle(index: int, payload_blocks: int = 40) -> list[BaseMessage]:
    """一轮真实形态的工具往返：读取若干排版块并返回大块 JSON。"""
    call_id = f"call-{index}"
    result = json.dumps(
        {
            "ok": True,
            "revision": f"rev-{index}",
            "blocks": [
                {
                    "block_id": f"b-{index}-{item}",
                    "tag": "p",
                    "path": f"section:nth-of-type(1) > p:nth-of-type({item})",
                    "html": f"<p>第 {index} 轮第 {item} 块的完整源码，" + ("填充内容" * 20) + "</p>",
                    "expected_hash": f"hash-{index}-{item}",
                }
                for item in range(payload_blocks)
            ],
        },
        ensure_ascii=False,
    )
    return [
        AIMessage(
            content="",
            tool_calls=[{"id": call_id, "name": "read_blocks", "args": {"block_ids": [f"b-{index}-0"]}}],
        ),
        ToolMessage(content=result, tool_call_id=call_id, name="read_blocks"),
    ]


def _conversation(cycle_count: int) -> list[BaseMessage]:
    messages: list[BaseMessage] = [
        SystemMessage(content="系统规则" * 50),
        HumanMessage(content="上一轮的历史请求"),
        AIMessage(content="上一轮的历史回复"),
        HumanMessage(content="本轮请求：请调整全文标题层级"),
    ]
    for index in range(cycle_count):
        messages.extend(_cycle(index))
    return messages


def _tokens(messages: list[BaseMessage]) -> int:
    total = 0
    for message in messages:
        total += estimate_tokens(str(message.content))
        for call in getattr(message, "tool_calls", None) or []:
            total += estimate_tokens(json.dumps(call.get("args", {}), ensure_ascii=False))
    return total


def _assert_tool_pairing(case: unittest.TestCase, messages: list[BaseMessage]) -> None:
    """每个 tool_call 都必须紧随其后被应答，且没有孤立的 ToolMessage。"""
    answered: set[str] = set()
    pending: set[str] = set()
    for message in messages:
        if isinstance(message, ToolMessage):
            case.assertIn(
                message.tool_call_id,
                pending,
                f"ToolMessage {message.tool_call_id} 没有对应的 tool_call，provider 会拒绝该请求",
            )
            pending.discard(message.tool_call_id)
            answered.add(message.tool_call_id)
            continue
        case.assertFalse(pending, f"tool_call {pending} 未被应答就出现了下一条消息")
        for call in getattr(message, "tool_calls", None) or []:
            pending.add(str(call["id"]))
    case.assertFalse(pending, f"末尾仍有未应答的 tool_call：{pending}")


class RunCompactionTests(unittest.TestCase):
    class _Compactor:
        async def ainvoke(self, _messages):
            return AIMessage(content=json.dumps({
                "objective": "完成当前排版",
                "constraints": "历史定位信息可能过期",
                "decisions": "重新读取当前块",
                "completed": "早期工具循环已完成",
                "active_work": "继续处理最新循环",
                "blockers": "无",
                "next_steps": "继续当前工具链",
                "source_refs": "",
            }, ensure_ascii=False))

    class _FailingCompactor:
        async def ainvoke(self, _messages):
            raise RuntimeError("provider unavailable")

    class _FalseThinkingRejectedCompactor:
        async def ainvoke(self, _messages):
            raise RuntimeError(
                "Error code: 400 - The value of the enable_thinking parameter is restricted to True."
            )

    class _FallbackCompactor:
        async def ainvoke(self, _messages):
            return AIMessage(content='{"objective":"fallback"}')

    def test_compaction_model_uses_bounded_non_streaming_transport(self) -> None:
        provider = SimpleNamespace()
        model = SimpleNamespace(max_output_tokens=16_384)
        sentinel = object()
        with patch("app.services.chat_agent.build_chat_model", return_value=(sentinel, object())) as build:
            result = build_compaction_model(provider, model)

        self.assertIs(result, sentinel)
        build.assert_called_once_with(
            provider,
            model,
            "disabled",
            max_retries=COMPACTION_MODEL_MAX_RETRIES,
            request_timeout_seconds=COMPACTION_MODEL_REQUEST_TIMEOUT_SECONDS,
            max_completion_tokens=COMPACTION_MODEL_MAX_OUTPUT_TOKENS,
            streaming=False,
        )

    def test_compaction_retries_without_disabled_thinking_parameter_after_gateway_rejection(self) -> None:
        provider = SimpleNamespace()
        model = SimpleNamespace(
            model_name="qwen3.8-max-preview",
            max_output_tokens=16_384,
            thinking_config={"disabled": {"enable_thinking": False}},
        )
        fallback = self._FallbackCompactor()
        with patch(
            "app.services.chat_agent.build_chat_model",
            side_effect=[(self._FalseThinkingRejectedCompactor(), object()), (fallback, object())],
        ) as build:
            compactor = build_compaction_model(provider, model)
            # The auto fallback is constructed before the request's database
            # session can be committed and released.
            self.assertEqual(build.call_count, 2)
            response = asyncio.run(compactor.ainvoke([]))

        self.assertEqual(response.content, '{"objective":"fallback"}')
        self.assertEqual(build.call_count, 2)
        self.assertEqual(build.call_args_list[0].args[2], "disabled")
        self.assertEqual(build.call_args_list[1].args[2], "auto")
        self.assertEqual(
            thinking_capability_fallback_data(7, compactor),
            {
                "model_id": 7,
                "reason": "enable_thinking_false",
                "fallback_mode": "auto",
                "message": "该模型不支持不思考，已使用默认思考参数完成本次请求",
            },
        )

    def test_native_disabled_thinking_config_uses_the_same_compaction_fallback(self) -> None:
        provider = SimpleNamespace()
        model = SimpleNamespace(
            model_name="deepseek-v4-pro",
            max_output_tokens=16_384,
            thinking_config={"disabled": {"thinking": {"type": "disabled"}}},
            supports_disabled_thinking=True,
        )
        fallback = self._FallbackCompactor()
        with patch(
            "app.services.chat_agent.build_chat_model",
            side_effect=[(self._FalseThinkingRejectedCompactor(), object()), (fallback, object())],
        ) as build:
            compactor = build_compaction_model(provider, model)
            response = asyncio.run(compactor.ainvoke([]))

        self.assertEqual(response.content, '{"objective":"fallback"}')
        self.assertEqual(build.call_count, 2)
        self.assertEqual(build.call_args_list[1].args[2], "auto")

    def test_compaction_502_has_a_recoverable_public_error(self) -> None:
        detail = compaction_failure_detail(RuntimeError("Error code: 502 - Bad Gateway"))

        self.assertEqual(detail, "压缩模型服务暂时不可用（上游 502），可重试")

    def test_model_compaction_keeps_pairs_and_never_mutates_graph_state(self) -> None:
        messages = _conversation(8)
        head, cycles = _split_run_cycles(messages)
        budget = _tokens([*head, *[message for cycle in cycles[-RUN_VERBATIM_CYCLE_COUNT:] for message in cycle]]) + 1_000

        compacted, stats = asyncio.run(
            compact_run_messages_with_model(messages, budget, self._Compactor())
        )

        self.assertTrue(stats["compacted"])
        self.assertGreater(stats["summarized_cycles"], 0)
        self.assertEqual(stats["dropped_cycles"], 0)
        self.assertLessEqual(stats["used_tokens"], budget)
        self.assertEqual(len(messages), 4 + 8 * 2)
        _assert_tool_pairing(self, compacted)
        self.assertIsInstance(compacted[1], SystemMessage)

    def test_new_work_over_budget_is_summarized_instead_of_silently_dropped(self) -> None:
        messages = _conversation(8)
        head, cycles = _split_run_cycles(messages)
        budget = _tokens([
            *head,
            *(message for cycle in cycles[-RUN_VERBATIM_CYCLE_COUNT:] for message in cycle),
        ]) + 1_000
        compactor = self._Compactor()
        compactor.ainvoke = AsyncMock(wraps=compactor.ainvoke)

        first_projection, _ = asyncio.run(
            compact_run_messages_with_model(messages, budget, compactor)
        )
        next_projection, next_stats = asyncio.run(
            compact_run_messages_with_model([*first_projection, *_cycle(99)], budget, compactor)
        )

        self.assertEqual(compactor.ainvoke.await_count, 2)
        self.assertGreater(next_stats["summarized_cycles"], 0)
        self.assertEqual(next_stats["dropped_cycles"], 0)
        self.assertEqual(sum(isinstance(m, SystemMessage) and str(m.content).startswith("以下是较早工具循环") for m in next_projection), 1)
        _assert_tool_pairing(self, next_projection)

    def test_second_model_compaction_merges_previous_runtime_summary(self) -> None:
        marker = "首批图片已生成且标题已修改"

        class MergingCompactor:
            prompts: list[str] = []

            async def ainvoke(self, messages):
                prompt = str(messages[-1].content)
                self.prompts.append(prompt)
                completed = marker if len(self.prompts) == 1 or marker in prompt else "早期进展已丢失"
                return AIMessage(content=json.dumps({
                    "objective": "完成当前排版",
                    "constraints": "保留原文",
                    "decisions": "重新读取当前块",
                    "completed": completed,
                    "active_work": "继续处理最新循环",
                    "blockers": "无",
                    "next_steps": "继续当前工具链",
                    "source_refs": "",
                }, ensure_ascii=False))

        messages = _conversation(8)
        head, cycles = _split_run_cycles(messages)
        budget = _tokens([
            *head, *(message for cycle in cycles[-RUN_VERBATIM_CYCLE_COUNT:] for message in cycle),
        ]) + 1_000
        compactor = MergingCompactor()
        first, _ = asyncio.run(compact_run_messages_with_model(messages, budget, compactor))
        second, stats = asyncio.run(compact_run_messages_with_model([*first, *_cycle(99)], budget, compactor))

        self.assertEqual(len(compactor.prompts), 2)
        self.assertIn(marker, compactor.prompts[1])
        self.assertIn("已有本轮运行工作摘要", compactor.prompts[1])
        self.assertIn(marker, second[1].content)
        self.assertGreater(stats["summarized_cycles"], 0)
        self.assertEqual(stats["dropped_cycles"], 0)
        _assert_tool_pairing(self, second)

    def test_reused_summary_does_not_emit_a_second_compaction_card(self) -> None:
        """A later structural trim must not look like another model summary."""
        summary = '{"objective":"继续处理当前任务"}'
        state = {"last_announced": summary}

        self.assertFalse(
            _should_publish_runtime_compaction(
                {
                    "compacted": True,
                    "fallback": "existing_summary",
                    "summary": summary,
                    "summarized_cycles": 0,
                    "digested_cycles": 4,
                },
                state,
            )
        )
        self.assertEqual(state["last_announced"], summary)

    def test_first_model_summary_emits_one_compaction_card(self) -> None:
        state: dict[str, object] = {}
        compaction = {
            "compacted": True,
            "summary": '{"objective":"继续处理当前任务"}',
            "summarized_cycles": 5,
        }

        self.assertTrue(_should_publish_runtime_compaction(compaction, state))
        self.assertFalse(_should_publish_runtime_compaction(compaction, state))

    def test_model_compaction_failure_never_uses_deterministic_fallback(self) -> None:
        messages = _conversation(8)
        with self.assertRaisesRegex(RuntimeCompactionError, "运行中上下文压缩失败"):
            asyncio.run(compact_run_messages_with_model(messages, _tokens(messages) // 2, self._FailingCompactor()))

    def test_tool_schema_cost_triggers_compaction_before_the_provider_limit(self) -> None:
        """Tool JSON Schema is request input even though it is not a message."""
        messages = _conversation(2)
        message_tokens = _tokens(messages)
        provider_threshold = 176_000
        legacy_budget = provider_threshold - 3_500
        # Reproduces the production failure: message-only accounting fits the
        # old budget while the request with tools already exceeds the provider.
        tool_schema_tokens = provider_threshold - message_tokens + 1

        self.assertLess(message_tokens, legacy_budget)
        self.assertGreater(message_tokens + tool_schema_tokens, provider_threshold)
        effective_budget = _effective_run_input_budget(provider_threshold, tool_schema_tokens)
        self.assertLess(effective_budget, message_tokens)

        _, stats = asyncio.run(
            compact_run_messages_with_model(messages, effective_budget, self._Compactor())
        )

        self.assertTrue(stats["compacted"])

    def test_tool_preview_budget_uses_compacted_runtime_projection(self) -> None:
        """A compacted run must not keep charging dropped audit cycles."""
        old_history = _conversation(8)
        runtime_projection = [
            SystemMessage(content="系统规则"),
            HumanMessage(content="本轮请求"),
            AIMessage(content="已定位目标"),
        ]

        limit = _dynamic_tool_result_limit(
            runtime_projection,
            old_history,
            run_budget_tokens=5_000,
            tool_count=1,
            max_preview_tokens=4_096,
        )

        self.assertGreater(limit, 256)
        self.assertEqual(
            _dynamic_tool_result_limit(
                None,
                old_history,
                run_budget_tokens=5_000,
                tool_count=1,
                max_preview_tokens=4_096,
            ),
            256,
        )
        self.assertEqual(
            limit,
            min(4_096, max(256, (5_000 - _tokens(runtime_projection)))),
        )

    def test_tool_preview_budget_uses_provider_priced_remainder_directly(self) -> None:
        runtime_projection = [
            SystemMessage(content="系统规则"),
            HumanMessage(content="本轮请求"),
        ]
        limit = _dynamic_tool_result_limit(
            runtime_projection,
            [],
            run_budget_tokens=_provider_message_tokens(runtime_projection[0], 1.6)
            + _provider_message_tokens(runtime_projection[1], 1.6)
            + 1_600,
            tool_count=1,
            max_preview_tokens=4_096,
            token_estimate_multiplier=1.6,
        )

        provider_remainder = 1_600
        self.assertEqual(limit, provider_remainder)

    def test_runtime_message_tokens_include_multimodal_image_cost(self) -> None:
        message = HumanMessage(
            content=[
                {"type": "text", "text": "请检查图片"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ]
        )

        self.assertEqual(
            _message_tokens(message),
            estimate_tokens("请检查图片") + 1_024,
        )

    def test_provider_token_safety_factor_triggers_compaction_before_provider_limit(self) -> None:
        """Chinese HTML can cost more than the neutral cl100k estimate."""
        messages = _conversation(2)
        local_tokens = _tokens(messages)
        budget = int(local_tokens * 1.3)

        _, local_stats = compact_run_messages(messages, budget)
        _, provider_stats = compact_run_messages(
            messages, budget, token_estimate_multiplier=1.6
        )

        self.assertFalse(local_stats["compacted"])
        self.assertTrue(provider_stats["compacted"])

    def test_under_budget_conversation_is_returned_unchanged(self) -> None:
        messages = _conversation(2)
        budget = _tokens(messages) + 1_000

        compacted, stats = compact_run_messages(messages, budget)

        self.assertEqual(compacted, messages)
        self.assertFalse(stats["compacted"])
        self.assertEqual(stats["digested_cycles"], 0)
        self.assertEqual(stats["dropped_cycles"], 0)

    def test_runtime_compaction_starts_at_configured_budget(self) -> None:
        messages = _conversation(8)
        measured = sum(_provider_message_tokens(message, 1.0) for message in messages)
        compactor = self._Compactor()

        _, below = asyncio.run(compact_run_messages_with_model(
            messages, measured + 1, compactor, token_estimate_multiplier=1.0,
        ))
        self.assertFalse(below["compacted"])

        _, at_threshold = asyncio.run(compact_run_messages_with_model(
            messages, measured, compactor, token_estimate_multiplier=1.0,
        ))
        self.assertTrue(at_threshold["compacted"])
        self.assertLess(at_threshold["used_tokens"], measured)

        _, structural = compact_run_messages(messages, measured, token_estimate_multiplier=1.0)
        self.assertTrue(structural["compacted"])

    def test_over_budget_conversation_is_brought_within_budget(self) -> None:
        messages = _conversation(12)
        budget = _tokens(messages) // 4

        compacted, stats = compact_run_messages(messages, budget)

        self.assertTrue(stats["compacted"])
        self.assertLessEqual(stats["used_tokens"], budget)
        self.assertLess(stats["used_tokens"], stats["original_tokens"])
        _assert_tool_pairing(self, compacted)

    def test_tool_pairing_survives_every_budget(self) -> None:
        messages = _conversation(10)
        full = _tokens(messages)
        for divisor in (1, 2, 3, 5, 8, 20, 50):
            with self.subTest(divisor=divisor):
                compacted, _ = compact_run_messages(messages, max(1, full // divisor))
                _assert_tool_pairing(self, compacted)

    def test_system_prompt_and_current_request_are_never_dropped(self) -> None:
        messages = _conversation(12)

        compacted, _ = compact_run_messages(messages, 1)

        self.assertIsInstance(compacted[0], SystemMessage)
        self.assertEqual(compacted[0].content, messages[0].content)
        human = [item.content for item in compacted if isinstance(item, HumanMessage)]
        self.assertIn("本轮请求：请调整全文标题层级", human)

    def test_newest_cycle_stays_verbatim_while_the_budget_allows_it(self) -> None:
        """摘要older轮就够用时，最新一轮必须原样保留。

        模型正要基于最新一轮的 block_id 与 expected_hash 继续推理，过早摘要
        会逼它重新 read_blocks，白费一轮往返。
        """
        messages = _conversation(8)
        newest_result = messages[-1].content
        # 预算精确取「只摘要早期轮」这一趟的结果，确保第二趟不会被触发。
        head, cycles = _split_run_cycles(messages)
        verbatim_from = max(0, len(cycles) - RUN_VERBATIM_CYCLE_COUNT)
        first_pass = [
            *head,
            *(
                message
                for index, cycle in enumerate(cycles)
                for message in (_digest_cycle(cycle) if index < verbatim_from else cycle)
            ),
        ]
        budget = _tokens(first_pass)
        self.assertLess(budget, _tokens(messages))

        compacted, stats = compact_run_messages(messages, budget)

        self.assertGreater(stats["digested_cycles"], 0)
        self.assertEqual(stats["dropped_cycles"], 0)
        self.assertEqual(compacted[-1].content, newest_result)

    def test_newest_cycle_is_digested_rather_than_dropped_when_budget_is_tight(self) -> None:
        """预算装不下时，宁可把最新一轮摘要掉，也不整轮丢弃。

        丢弃会让模型完全看不到刚做过什么；摘要至少保住 revision 与 block_id。
        """
        messages = _conversation(8)

        compacted, stats = compact_run_messages(messages, _tokens(messages) // 20)

        self.assertGreater(stats["digested_cycles"], 0)
        _assert_tool_pairing(self, compacted)
        # 最后一条仍是工具结果，只是被压成了摘要。
        self.assertIsInstance(compacted[-1], ToolMessage)
        self.assertIn("revision=", compacted[-1].content)

    def test_digest_keeps_revision_and_block_ids_for_repositioning(self) -> None:
        messages = _conversation(8)

        compacted, _ = compact_run_messages(messages, _tokens(messages) // 3)

        digests = [
            item.content
            for item in compacted
            if isinstance(item, ToolMessage) and len(item.content) < 400
        ]
        self.assertTrue(digests, "预期较早的工具结果被折叠成摘要")
        joined = "\n".join(digests)
        self.assertIn("revision=", joined)
        self.assertIn("涉及块", joined)
        self.assertIn("read_blocks", joined)

    def test_digest_never_leaks_full_source_html(self) -> None:
        messages = _conversation(8)

        compacted, _ = compact_run_messages(messages, _tokens(messages) // 3)

        digested = [
            item.content
            for item in compacted
            if isinstance(item, ToolMessage) and "填充内容" not in item.content
        ]
        self.assertTrue(digested)

    def test_zero_or_negative_budget_is_treated_as_no_limit(self) -> None:
        messages = _conversation(3)

        for budget in (0, -1):
            with self.subTest(budget=budget):
                compacted, stats = compact_run_messages(messages, budget)
                self.assertEqual(compacted, messages)
                self.assertFalse(stats["compacted"])


if __name__ == "__main__":
    unittest.main()
