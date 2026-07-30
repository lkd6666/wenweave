"""System prompt 的可缓存前缀。

Prompt 缓存只匹配前缀：静态规则必须整段排在任何易变内容之前，否则文档地图
一变就让后面全部失效。一次 run 会按工具轮数重复发送整个 system prompt，
所以这个顺序直接决定输入成本与首 token 延迟。
"""
from __future__ import annotations

import unittest

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage

from app.services.chat_agent import (
    build_static_system_prompt,
    build_system_message,
    build_system_prompt,
    build_volatile_system_prompt,
)
from app.services.openai_compatible_chat_model import OpenAICompatibleChatModel
from app.services.token_budget import estimate_tokens

_HTML = "<section><h1>标题</h1><p>正文</p></section>"


def _anthropic() -> ChatAnthropic:
    return ChatAnthropic(model_name="claude-sonnet-5", api_key="test-key")


def _openai() -> OpenAICompatibleChatModel:
    return OpenAICompatibleChatModel(model="gpt-5", api_key="test-key")


class PromptCachingTests(unittest.TestCase):
    def test_static_half_carries_the_bulk_of_the_prompt(self) -> None:
        static_tokens = estimate_tokens(build_static_system_prompt())
        volatile_tokens = estimate_tokens(build_volatile_system_prompt("标题", _HTML))

        # 排版规范（最大的静态块）必须落在可缓存的一侧。
        self.assertGreater(static_tokens, volatile_tokens)
        self.assertGreater(static_tokens, 4_000)

    def test_static_half_contains_no_volatile_section(self) -> None:
        static_prompt = build_static_system_prompt()

        for header in ("## 当前文档", "## 压缩工作记忆", "## 本轮选中元素", "## 外部排版参考"):
            self.assertNotIn(header, static_prompt)

    def test_combined_prompt_puts_every_static_token_before_the_first_volatile_one(self) -> None:
        prompt = build_system_prompt("标题", _HTML)
        static_prompt = build_static_system_prompt()

        self.assertTrue(prompt.startswith(static_prompt))
        # 文档地图必须整体位于静态段之后。
        self.assertGreater(prompt.index("## 当前文档"), len(static_prompt) - 1)

    def test_anthropic_gets_one_cache_breakpoint_on_the_static_block_only(self) -> None:
        message = build_system_message(_anthropic(), "标题", _HTML)

        self.assertIsInstance(message, SystemMessage)
        blocks = message.content
        self.assertIsInstance(blocks, list)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["cache_control"], {"type": "ephemeral"})
        # 断点必须只落在静态块：加在易变块上等于每轮都写入新缓存条目。
        self.assertNotIn("cache_control", blocks[1])
        self.assertEqual(blocks[0]["text"], build_static_system_prompt())

    def test_openai_compatible_gets_a_plain_string(self) -> None:
        message = build_system_message(_openai(), "标题", _HTML)

        # 部分兼容服务会拒绝 block 形式的 system 内容；它们自动缓存长前缀。
        self.assertIsInstance(message.content, str)
        self.assertTrue(message.content.startswith(build_static_system_prompt()))

    def test_volatile_content_never_reaches_the_cached_block(self) -> None:
        message = build_system_message(
            _anthropic(),
            "机密标题",
            _HTML,
            memory={"user_preferences": ["偏好蓝色标题"]},
        )

        cached = message.content[0]["text"]
        self.assertNotIn("机密标题", cached)
        self.assertNotIn("偏好蓝色标题", cached)


if __name__ == "__main__":
    unittest.main()
