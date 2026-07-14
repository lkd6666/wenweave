"""OpenAI Chat Completions 协议兼容适配器：适用于 DeepSeek/Qwen/Kimi/GLM/自建 vLLM 等
任何暴露 `{base_url}/chat/completions` 接口且遵循 OpenAI 请求/响应格式的服务端。"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.services.ai_client.base import ChatResult, StreamEvent, ToolCall


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_payload(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: Optional[int],
        stream: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        payload.update(kwargs)
        return payload

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> ChatResult:
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(model, messages, tools, max_tokens, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        tool_calls: List[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": func.get("arguments")}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=func.get("name", ""), arguments=args))

        return ChatResult(content=content, tool_calls=tool_calls, raw=data, finish_reason=choice.get("finish_reason"))

    async def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(model, messages, tools, max_tokens, stream=True, **kwargs)

        # OpenAI 流式协议里 tool_call 的参数是按 index 分片、逐字符增量返回的，需要自行累积拼接。
        pending_tool_calls: Dict[int, Dict[str, Any]] = {}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason")

                    if delta.get("content"):
                        yield StreamEvent(type="text_delta", text_delta=delta["content"])

                    for tc_delta in delta.get("tool_calls") or []:
                        idx = tc_delta.get("index", 0)
                        entry = pending_tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc_delta.get("id"):
                            entry["id"] = tc_delta["id"]
                        func = tc_delta.get("function") or {}
                        if func.get("name"):
                            entry["name"] = func["name"]
                        if func.get("arguments"):
                            entry["arguments"] += func["arguments"]

                    if finish_reason:
                        tool_calls: List[ToolCall] = []
                        for entry in pending_tool_calls.values():
                            try:
                                args = json.loads(entry["arguments"] or "{}")
                            except json.JSONDecodeError:
                                args = {"_raw": entry["arguments"]}
                            tool_calls.append(ToolCall(id=entry["id"], name=entry["name"], arguments=args))
                        yield StreamEvent(type="done", tool_calls=tool_calls, finish_reason=finish_reason)
