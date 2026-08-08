"""补充 OpenAI 兼容服务的非标准流式推理字段。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI


class OpenAICompatibleChatModel(ChatOpenAI):
    """保留兼容接口在 SSE delta 中返回的 reasoning_content。

    ``ChatOpenAI`` 只实现 OpenAI 官方 Chat Completions 字段，转换 chunk 时会丢弃
    兼容厂商附加的 ``reasoning_content``。Responses API 的标准事件由父类处理；
    这里仅补充 Chat Completions 的非标准字段。
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> Any:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None or not isinstance(generation_chunk.message, AIMessageChunk):
            return generation_chunk

        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        delta = choices[0].get("delta") if choices else None
        if not isinstance(delta, dict):
            return generation_chunk

        for field in ("reasoning_content", "reasoning", "thinking", "thought"):
            value = delta.get(field)
            if isinstance(value, str) and value:
                generation_chunk.message.additional_kwargs[field] = value
                break
        return generation_chunk
