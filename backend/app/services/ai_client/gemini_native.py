"""Google Gemini's native GenerateContent HTTP adapter.

The application keeps an OpenAI-shaped message contract above this layer.  This
adapter translates that contract to Gemini ``contents``/``functionCall``
objects so connection tests and non-Agent callers use the same provider path as
the native LangChain model.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.services.ai_client.base import ChatResult, StreamEvent, ToolCall


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_text_from_content(item) for item in content)
    if isinstance(content, dict):
        return str(content.get("text") or "")
    return ""


def _part_from_block(block: Any) -> dict[str, Any] | None:
    if isinstance(block, str):
        return {"text": block} if block else None
    if not isinstance(block, dict):
        return None
    block_type = str(block.get("type") or "")
    if block_type in {"text", "input_text", "output_text"}:
        text = block.get("text")
        return {"text": text} if isinstance(text, str) and text else None
    if block_type in {"image_url", "input_image"}:
        image_url = block.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        if not isinstance(image_url, str) or not image_url.startswith("data:"):
            return None
        header, encoded = image_url.split(",", 1)
        mime_type = header[5:].split(";", 1)[0] or "application/octet-stream"
        return {"inlineData": {"mimeType": mime_type, "data": encoded}}
    return None


def messages_to_gemini(
    messages: List[Dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            text = _text_from_content(message.get("content"))
            if text:
                system_parts.append({"text": text})
            continue
        if role == "tool":
            name = str(message.get("name") or "tool")
            raw = str(message.get("content") or "")
            try:
                response = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                response = {"result": raw}
            function_response: dict[str, Any] = {"name": name, "response": response}
            call_id = str(message.get("tool_call_id") or "")
            if call_id:
                function_response["id"] = call_id
            contents.append({"role": "user", "parts": [{"functionResponse": function_response}]})
            continue

        native_role = "model" if role == "assistant" else "user"
        parts: list[dict[str, Any]] = []
        tool_calls = message.get("tool_calls") or []
        if native_role == "model" and isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") or tool_call
                arguments = function.get("arguments", tool_call.get("args", {}))
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                call = {"name": str(function.get("name") or ""), "args": arguments or {}}
                call_id = str(tool_call.get("id") or tool_call.get("call_id") or "")
                if call_id:
                    call["id"] = call_id
                call_part: dict[str, Any] = {"functionCall": call}
                signatures = message.get("gemini_thought_signatures")
                if isinstance(signatures, dict):
                    signature = signatures.get(call_id) or signatures.get(str(call["name"]))
                    if isinstance(signature, str) and signature:
                        call_part["thoughtSignature"] = signature
                parts.append(call_part)
        content = message.get("content")
        blocks = content if isinstance(content, list) else [content]
        for block in blocks:
            part = _part_from_block(block)
            if part:
                parts.append(part)
        if parts:
            contents.append({"role": native_role, "parts": parts})
    return ({"parts": system_parts} if system_parts else None), contents


def tools_to_gemini(tools: Optional[List[Dict[str, Any]]]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    declarations: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        function = item.get("function") or item
        declaration: dict[str, Any] = {
            "name": function.get("name"),
            "description": function.get("description", ""),
            "parameters": function.get("parameters", {"type": "object", "properties": {}}),
        }
        declarations.append(declaration)
    return [{"functionDeclarations": declarations}] if declarations else None


def _parts_from_response(data: dict[str, Any]) -> tuple[str, list[ToolCall], str, list[str]]:
    text_parts: list[str] = []
    thought_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    candidates = data.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    content = candidate.get("content") or {}
    for part in content.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if part.get("thought") is True:
            if isinstance(part.get("text"), str):
                thought_parts.append(part["text"])
            continue
        if isinstance(part.get("text"), str):
            text_parts.append(part["text"])
        call = part.get("functionCall")
        if isinstance(call, dict) and call.get("name"):
            tool_calls.append(
                ToolCall(
                    id=str(call.get("id") or ""),
                    name=str(call["name"]),
                    arguments=call.get("args") if isinstance(call.get("args"), dict) else {},
                )
            )
    return "".join(text_parts), tool_calls, str(candidate.get("finishReason") or ""), thought_parts


class GeminiNativeClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    def _build_payload(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: Optional[int],
        stream: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        system_instruction, contents = messages_to_gemini(messages)
        payload: Dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        generation_config = dict(kwargs.pop("generationConfig", kwargs.pop("generation_config", {})) or {})
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if generation_config:
            payload["generationConfig"] = generation_config
        converted_tools = tools_to_gemini(tools)
        if converted_tools:
            payload["tools"] = converted_tools
        payload.update(kwargs)
        return payload

    def _url(self, model: str, method: str, stream: bool = False) -> str:
        model_name = model.removeprefix("models/")
        suffix = f"models/{model_name}:{'streamGenerateContent?alt=sse' if stream else method}"
        return f"{self.base_url}/{suffix}"

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = self._build_payload(model, messages, tools, max_tokens, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self._url(model, "generateContent"), headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
        content, tool_calls, finish_reason, _ = _parts_from_response(data)
        return ChatResult(content=content, tool_calls=tool_calls, raw=data, finish_reason=finish_reason)

    async def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        payload = self._build_payload(model, messages, tools, max_tokens, stream=True, **kwargs)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", self._url(model, "generateContent", stream=True), headers=self._headers(), json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    content, tool_calls, finish_reason, thoughts = _parts_from_response(data)
                    for thought in thoughts:
                        if thought:
                            yield StreamEvent(type="reasoning_delta", reasoning_delta=thought)
                    if content:
                        yield StreamEvent(type="text_delta", text_delta=content)
                    if tool_calls or finish_reason:
                        yield StreamEvent(type="done", tool_calls=tool_calls, finish_reason=finish_reason or "STOP")
