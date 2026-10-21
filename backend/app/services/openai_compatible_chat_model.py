"""补充 OpenAI 兼容服务的非标准流式推理字段。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

RUNTIME_CONTEXT_MARKER = "_agent_runtime_context"
CACHE_BOUNDARIES_MARKER = "_agent_cache_boundaries"
CACHE_BOUNDARY_TEXT = "【服务端工具结果边界：继续既有用户任务】"


def tool_result_group_count(messages: list[BaseMessage]) -> int:
    return sum(isinstance(item, ToolMessage) and (
        index + 1 == len(messages) or not isinstance(messages[index + 1], ToolMessage))
        for index, item in enumerate(messages))


def runtime_cache_boundaries_enabled(messages: list[BaseMessage]) -> bool:
    return any(isinstance(item, HumanMessage) and item.additional_kwargs.get(RUNTIME_CONTEXT_MARKER)
               and item.additional_kwargs.get(CACHE_BOUNDARIES_MARKER, True) for item in messages)


def runtime_cache_boundary_count(messages: list[BaseMessage]) -> int:
    """One transport checkpoint per complete consecutive tool-result group."""
    if not runtime_cache_boundaries_enabled(messages):
        return 0
    return tool_result_group_count(messages)


def runtime_context_wire_role(model_name: str) -> str:
    """Avoid treating server data as an assistant prefill on other protocols."""
    name = model_name.lower().rsplit("/", 1)[-1]
    return "assistant" if name.startswith(("gpt-", "o1", "o3", "o4")) else "user"


def project_runtime_cache_messages(messages: list[BaseMessage], *, context_role: str = "assistant") -> list[BaseMessage]:
    """Build deterministic wire-only boundaries without modifying audit history."""
    if not any(isinstance(item, HumanMessage) and item.additional_kwargs.get(RUNTIME_CONTEXT_MARKER)
               for item in messages):
        return messages
    projected = []
    boundaries_enabled = runtime_cache_boundaries_enabled(messages)
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage) and message.additional_kwargs.get(RUNTIME_CONTEXT_MARKER):
            projected.append((AIMessage if context_role == "assistant" else HumanMessage)(content=message.content))
        else:
            projected.append(message)
        if boundaries_enabled and isinstance(message, ToolMessage) and (
                index + 1 == len(messages) or not isinstance(messages[index + 1], ToolMessage)):
            projected.append(HumanMessage(content=CACHE_BOUNDARY_TEXT))
    return projected


def _reasoning_delta_value(value: Any) -> str:
    """Extract provider-supplied reasoning text without inventing a summary."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_reasoning_delta_value(item) for item in value)
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "reasoning", "thinking", "reasoning_content"):
        text = _reasoning_delta_value(value.get(key))
        if text:
            return text
    return _reasoning_delta_value(value.get("summary"))


class OpenAICompatibleChatModel(ChatOpenAI):
    """保留兼容接口在 SSE delta 中返回的 reasoning_content。

    ``ChatOpenAI`` 只实现 OpenAI 官方 Chat Completions 字段，转换 chunk 时会丢弃
    兼容厂商附加的 ``reasoning_content``。Responses API 的标准事件由父类处理；
    这里仅补充 Chat Completions 的非标准字段。
    """

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None,
                             **kwargs: Any) -> dict:
        """Project server state using the provider's supported message role.

        Internally it remains a marked HumanMessage for budgets and request
        exclusion. GPT transports see assistant data: otherwise the
        implicit cache write ends after the state that the next tool round
        removes, rather than after the reusable user/tool history. The fixed
        instructions identify this suffix as server data. Other protocols use
        a user suffix to avoid unsupported assistant prefill/reasoning rules.
        """
        messages = self._convert_input(input_).to_messages()
        projected = project_runtime_cache_messages(messages, context_role=runtime_context_wire_role(self.model_name))
        payload = super()._get_request_payload(projected, stop=stop, **kwargs)
        if "deepseek" in self.model_name.lower() and "messages" in payload:
            # ChatOpenAI omits this native field. Reuse actual recorded
            # reasoning, never fabricate it or mark server data as a prefill.
            for message, wire in zip(projected, payload["messages"]):
                if isinstance(message, AIMessage):
                    reasoning = message.additional_kwargs.get("reasoning_content")
                    if isinstance(reasoning, str):
                        wire["reasoning_content"] = reasoning
        return payload

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
            if _reasoning_delta_value(value):
                generation_chunk.message.additional_kwargs[field] = value
                break
        return generation_chunk
