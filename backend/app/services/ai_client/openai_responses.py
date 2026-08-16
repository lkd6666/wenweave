"""OpenAI Responses API adapter.

The rest of the application uses OpenAI-style messages and tool calls. This
adapter translates those values to Responses ``input`` items and normalises
the Responses SSE stream back to the small provider-neutral event contract.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.services.ai_client.base import ChatResult, StreamEvent, ToolCall


class OpenAIResponsesClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _content_for_input(content: Any, role: str) -> Any:
        if not isinstance(content, list):
            return content or ""

        blocks: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, str):
                blocks.append({"type": "input_text", "text": block})
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type in {"text", "input_text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str):
                    blocks.append({"type": "input_text", "text": text})
            elif block_type in {"image_url", "input_image"}:
                image_url = block.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                if isinstance(image_url, str) and image_url:
                    blocks.append({"type": "input_image", "image_url": image_url})
        if not blocks:
            return ""
        # Responses accepts a string for ordinary messages. Keep the compact
        # representation when possible, while preserving image blocks.
        if len(blocks) == 1 and blocks[0]["type"] == "input_text":
            return blocks[0]["text"]
        return blocks

    @classmethod
    def _build_input(cls, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            if role == "tool":
                converted.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(message.get("tool_call_id") or ""),
                        "output": str(message.get("content") or ""),
                    }
                )
                continue

            tool_calls = message.get("tool_calls") or []
            if role == "assistant" and isinstance(tool_calls, list):
                content = cls._content_for_input(message.get("content"), role)
                if content:
                    converted.append({"role": "assistant", "content": content})
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function") or tool_call
                    arguments = function.get("arguments", tool_call.get("args", {}))
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments or {}, ensure_ascii=False, separators=(",", ":"))
                    converted.append(
                        {
                            "type": "function_call",
                            "call_id": str(tool_call.get("id") or tool_call.get("call_id") or ""),
                            "name": str(function.get("name") or ""),
                            "arguments": arguments,
                        }
                    )
                continue

            converted.append(
                {
                    "role": role if role in {"system", "user", "assistant", "developer"} else "user",
                    "content": cls._content_for_input(message.get("content"), role),
                }
            )
        return converted

    @staticmethod
    def _convert_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        converted: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") != "function":
                converted.append(tool)
                continue
            function = tool.get("function") or tool
            item = {
                "type": "function",
                "name": function.get("name"),
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            }
            if "strict" in function:
                item["strict"] = function["strict"]
            converted.append(item)
        return converted or None

    @classmethod
    def _build_payload(
        cls,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: Optional[int],
        stream: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "input": cls._build_input(messages),
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        converted_tools = cls._convert_tools(tools)
        if converted_tools:
            payload["tools"] = converted_tools

        extra_body = kwargs.pop("extra_body", {})
        if isinstance(extra_body, dict):
            payload.update(extra_body)
        payload.update(kwargs)
        if "max_tokens" in payload:
            payload["max_output_tokens"] = payload.pop("max_tokens")
        if "max_completion_tokens" in payload:
            payload["max_output_tokens"] = payload.pop("max_completion_tokens")
        if "reasoning_effort" in payload and "reasoning" not in payload:
            payload["reasoning"] = {"effort": payload.pop("reasoning_effort")}
        return payload

    @staticmethod
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return {"_raw": str(raw or "")}
        return parsed if isinstance(parsed, dict) else {"_raw": str(raw or "")}

    @classmethod
    def _parse_output(cls, data: Dict[str, Any]) -> ChatResult:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for block in item.get("content") or []:
                    if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                        content_parts.append(str(block.get("text") or ""))
            elif item.get("type") == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=str(item.get("call_id") or item.get("id") or ""),
                        name=str(item.get("name") or ""),
                        arguments=cls._parse_arguments(item.get("arguments")),
                    )
                )
        return ChatResult(
            content="".join(content_parts),
            tool_calls=tool_calls,
            raw=data,
            finish_reason=str(data.get("status") or "") or None,
        )

    @staticmethod
    def _usage(response: Any) -> Optional[Dict[str, int]]:
        if not isinstance(response, dict):
            return None
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return None
        values = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
        if not all(isinstance(value, int) and value >= 0 for value in values.values()):
            return None
        details = usage.get("input_tokens_details") or {}
        return {
            **values,
            "cache_read_tokens": int(details.get("cached_tokens") or 0),
            "cache_write_tokens": int(details.get("cache_write_tokens") or 0),
        }

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> ChatResult:
        url = f"{self.base_url}/responses"
        payload = self._build_payload(model, messages, tools, max_tokens, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
        return self._parse_output(data)

    async def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self.base_url}/responses"
        payload = self._build_payload(model, messages, tools, max_tokens, stream=True, **kwargs)
        pending: Dict[str, Dict[str, Any]] = {}
        completed_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    event_type = str(event.get("type") or "")

                    if event_type == "response.output_text.delta":
                        text = event.get("delta")
                        if isinstance(text, str) and text:
                            yield StreamEvent(type="text_delta", text_delta=text)
                    elif event_type == "response.reasoning_summary_text.delta":
                        text = event.get("delta")
                        if isinstance(text, str) and text:
                            yield StreamEvent(type="reasoning_delta", reasoning_delta=text)
                    elif event_type == "response.output_item.added":
                        item = event.get("item") or {}
                        if isinstance(item, dict) and item.get("type") == "function_call":
                            call_id = str(item.get("call_id") or item.get("id") or "")
                            pending[call_id] = {
                                "id": call_id,
                                "item_id": str(item.get("id") or ""),
                                "name": str(item.get("name") or ""),
                                "arguments": str(item.get("arguments") or ""),
                            }
                    elif event_type == "response.function_call_arguments.delta":
                        call_id = str(event.get("call_id") or "")
                        item_id = str(event.get("item_id") or "")
                        key = call_id if call_id in pending else item_id
                        if key not in pending:
                            pending[key] = {"id": call_id, "item_id": item_id, "name": "", "arguments": ""}
                        if not pending[key].get("id") and call_id:
                            pending[key]["id"] = call_id
                        pending[key]["arguments"] += str(event.get("delta") or "")
                    elif event_type in {"response.output_item.done", "response.function_call_arguments.done"}:
                        item = event.get("item") or event
                        if event_type == "response.function_call_arguments.done" and isinstance(item, dict):
                            item = {**item, "type": "function_call"}
                        if not isinstance(item, dict) or item.get("type") not in {None, "function_call"}:
                            continue
                        call_id = str(item.get("call_id") or "")
                        item_id = str(item.get("item_id") or item.get("id") or "")
                        key = call_id if call_id in pending else item_id
                        entry = pending.setdefault(
                            key,
                            {"id": call_id, "item_id": item_id, "name": "", "arguments": ""},
                        )
                        if not entry.get("id") and call_id:
                            entry["id"] = call_id
                        if item.get("name"):
                            entry["name"] = str(item["name"])
                        if item.get("arguments"):
                            entry["arguments"] = str(item["arguments"])
                        if call_id and call_id not in completed_ids:
                            completed_ids.add(call_id)
                    elif event_type in {"response.completed", "response.incomplete"}:
                        calls = [
                            ToolCall(
                                id=str(entry["id"]),
                                name=str(entry["name"]),
                                arguments=self._parse_arguments(entry["arguments"]),
                            )
                            for entry in pending.values()
                            if entry.get("id") and entry.get("name")
                        ]
                        response_data = event.get("response") or {}
                        yield StreamEvent(
                            type="done",
                            tool_calls=calls,
                            finish_reason=str(response_data.get("status") or event_type.rsplit(".", 1)[-1]),
                            usage=self._usage(response_data),
                        )
