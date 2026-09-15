"""Small LangChain chat model for Google's native Gemini REST API."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Sequence

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from app.services.ai_client.gemini_native import messages_to_gemini, tools_to_gemini


def _message_dict(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": message.content}
    if isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "content": str(message.content or ""),
            "tool_call_id": str(message.tool_call_id or ""),
            "name": str(message.name or "tool"),
        }
    if isinstance(message, AIMessage):
        tool_calls: list[dict[str, Any]] = []
        for call in message.tool_calls or []:
            tool_calls.append(
                {
                    "id": call.get("id", ""),
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": json.dumps(call.get("args", {}), ensure_ascii=False, separators=(",", ":")),
                    },
                }
            )
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": tool_calls,
            "gemini_thought_signatures": message.additional_kwargs.get("gemini_thought_signatures", {}),
        }
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": message.content}
    return {"role": "user", "content": message.content}


def _response_parts(data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    candidates = data.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    content = candidate.get("content") or {}
    parts = [part for part in content.get("parts") or [] if isinstance(part, dict)]
    return parts, data.get("usageMetadata") or {}, str(candidate.get("finishReason") or "")


def _usage_metadata(raw: dict[str, Any]) -> dict[str, Any] | None:
    prompt = raw.get("promptTokenCount")
    output = raw.get("candidatesTokenCount")
    total = raw.get("totalTokenCount")
    if not all(isinstance(value, int) and value >= 0 for value in (prompt, output, total)):
        return None
    details: dict[str, Any] = {}
    thoughts = raw.get("thoughtsTokenCount")
    if isinstance(thoughts, int) and thoughts >= 0:
        details["reasoning"] = thoughts
    result: dict[str, Any] = {
        "input_tokens": prompt,
        "output_tokens": output,
        "total_tokens": total,
    }
    if details:
        result["output_token_details"] = details
    return result


def _visible_and_tools(parts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, str], str]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    signatures: dict[str, str] = {}
    thought_parts: list[str] = []
    for part in parts:
        text = part.get("text")
        if isinstance(text, str):
            if part.get("thought") is True:
                thought_parts.append(text)
            else:
                text_parts.append(text)
        call = part.get("functionCall")
        if isinstance(call, dict) and call.get("name"):
            call_id = str(call.get("id") or "")
            tool_calls.append(
                {
                    "name": str(call["name"]),
                    "args": call.get("args") if isinstance(call.get("args"), dict) else {},
                    "id": call_id,
                    "type": "tool_call",
                }
            )
            signature = part.get("thoughtSignature")
            if isinstance(signature, str) and signature:
                signatures[call_id or str(call["name"])] = signature
    return "".join(text_parts), tool_calls, signatures, "".join(thought_parts)


class GeminiNativeChatModel(BaseChatModel):
    model: str
    api_key: str
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    max_output_tokens: int = 8192
    timeout: float = 60.0
    streaming: bool = True
    generation_config: dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "gemini_native"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "base_url": self.base_url}

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    def _url(self, stream: bool) -> str:
        model_name = self.model.removeprefix("models/")
        operation = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"{self.base_url.rstrip('/')}/models/{model_name}:{operation}"

    def _payload(self, messages: list[BaseMessage], kwargs: dict[str, Any], stream: bool) -> dict[str, Any]:
        system_instruction, contents = messages_to_gemini([_message_dict(message) for message in messages])
        payload: dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        generation_config = dict(self.generation_config or {})
        configured = kwargs.pop("thinking_config", None)
        if isinstance(configured, dict):
            generation_config["thinkingConfig"] = dict(configured)
        if self.max_output_tokens > 0:
            generation_config.setdefault("maxOutputTokens", self.max_output_tokens)
        if generation_config:
            payload["generationConfig"] = generation_config
        tools = tools_to_gemini(kwargs.pop("tools", None))
        if tools:
            payload["tools"] = tools
        tool_choice = kwargs.pop("tool_choice", None)
        if tool_choice:
            mode = {"auto": "AUTO", "any": "ANY", "required": "ANY", "none": "NONE"}.get(str(tool_choice).lower())
            if mode:
                payload["toolConfig"] = {"functionCallingConfig": {"mode": mode}}
        payload.update(kwargs)
        return payload

    @staticmethod
    def _chunk_for_part(part: dict[str, Any], index: int = 0) -> AIMessageChunk | None:
        additional: dict[str, Any] = {}
        text = part.get("text")
        if isinstance(text, str) and text:
            if part.get("thought") is True:
                additional["thinking"] = text
                return AIMessageChunk(content="", additional_kwargs=additional)
            return AIMessageChunk(content=text)
        call = part.get("functionCall")
        if isinstance(call, dict) and call.get("name"):
            signature = part.get("thoughtSignature")
            if isinstance(signature, str) and signature:
                additional["gemini_thought_signatures"] = {
                    str(call.get("id") or call["name"]): signature
                }
            return AIMessageChunk(
                content="",
                additional_kwargs=additional,
                tool_call_chunks=[
                    {
                        "name": str(call["name"]),
                        "args": json.dumps(call.get("args") or {}, ensure_ascii=False, separators=(",", ":")),
                        "id": str(call.get("id") or ""),
                        "index": index,
                        "type": "tool_call_chunk",
                    }
                ],
            )
        return None

    def _result(self, data: dict[str, Any]) -> ChatResult:
        parts, raw_usage, finish_reason = _response_parts(data)
        text, tool_calls, signatures, thoughts = _visible_and_tools(parts)
        additional: dict[str, Any] = {}
        if thoughts:
            additional["thinking"] = thoughts
        if signatures:
            additional["gemini_thought_signatures"] = signatures
        message = AIMessage(
            content=text,
            tool_calls=tool_calls,
            additional_kwargs=additional,
            usage_metadata=_usage_metadata(raw_usage),
        )
        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output={"usage_metadata": raw_usage, "finish_reason": finish_reason},
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self._url(False), headers=self._headers(), json=self._payload(messages, dict(kwargs), False))
            response.raise_for_status()
            return self._result(response.json())

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self._url(False), headers=self._headers(), json=self._payload(messages, dict(kwargs), False))
            response.raise_for_status()
            return self._result(response.json())

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", self._url(True), headers=self._headers(), json=self._payload(messages, dict(kwargs), True)) as response:
                response.raise_for_status()
                for_index = 0
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    parts, raw_usage, _ = _response_parts(data)
                    for part in parts:
                        chunk = self._chunk_for_part(part, for_index)
                        if chunk is None:
                            continue
                        usage = _usage_metadata(raw_usage)
                        if usage:
                            chunk.usage_metadata = usage
                        for_index += 1
                        yield ChatGenerationChunk(message=chunk)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Any:
        converted = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(tools=converted, tool_choice=tool_choice, **kwargs)
