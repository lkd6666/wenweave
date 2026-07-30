"""Anthropic Messages API 适配器（Claude 系列模型），单独适配是因为其请求/响应格式
（system 独立字段、tool_use/input_json_delta 流式协议）与 OpenAI 协议不兼容。"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.services.ai_client.base import ChatResult, StreamEvent, ToolCall

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60.0,
        auth_style: str = "x-api-key",
    ):
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        # 国内云厂商的 Claude Code 兼容网关（阿里云百炼 / 智谱 / Kimi）文档只给出
        # ANTHROPIC_AUTH_TOKEN，即 Authorization: Bearer；官方 Anthropic 与 DeepSeek
        # 用 x-api-key。两者不通用，发错会直接 401，故由预设声明具体形式。
        self.auth_style = auth_style

    def _headers(self) -> Dict[str, str]:
        headers = {
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        if self.auth_style == "bearer":
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["x-api-key"] = self.api_key
        return headers

    @staticmethod
    def _split_system(messages: List[Dict[str, Any]]):
        system_parts = []
        chat_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_parts.append(m.get("content") or "")
            else:
                chat_messages.append(m)
        return ("\n\n".join(system_parts) if system_parts else None), chat_messages

    @staticmethod
    def _convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        把上层统一使用的 OpenAI 风格消息（assistant.tool_calls / role=tool）翻译成
        Anthropic Messages API 的 content-block 格式（tool_use / tool_result），
        使 chat_agent.py 等上层代码不需要关心具体厂商协议差异。
        """
        converted: List[Dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                blocks: List[Dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    func = tc.get("function", {})
                    try:
                        tool_input = json.loads(func.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        tool_input = {}
                    blocks.append(
                        {"type": "tool_use", "id": tc.get("id", ""), "name": func.get("name", ""), "input": tool_input}
                    )
                converted.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": m.get("content") or "",
                }
                # Anthropic 要求同一个 assistant 轮次产生的多个 tool_result 合并进同一条 user 消息
                if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                    converted[-1]["content"].append(tool_result_block)
                else:
                    converted.append({"role": "user", "content": [tool_result_block]})
            else:
                converted.append({"role": role, "content": m.get("content") or ""})
        return converted

    @staticmethod
    def _convert_tools(tools: Optional[List[Dict[str, Any]]]):
        if not tools:
            return None
        converted = []
        for t in tools:
            func = t.get("function", t)
            converted.append(
                {
                    "name": func.get("name"),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return converted

    def _build_payload(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: Optional[int],
        stream: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        system_prompt, chat_messages = self._split_system(messages)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(chat_messages),
            "max_tokens": max_tokens or 1024,
            "stream": stream,
        }
        if system_prompt:
            payload["system"] = system_prompt
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            payload["tools"] = converted_tools
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
        url = f"{self.base_url}/v1/messages"
        payload = self._build_payload(model, messages, tools, max_tokens, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        content_text = ""
        tool_calls: List[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.get("id", ""), name=block.get("name", ""), arguments=block.get("input", {}))
                )

        return ChatResult(content=content_text, tool_calls=tool_calls, raw=data, finish_reason=data.get("stop_reason"))

    async def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self.base_url}/v1/messages"
        payload = self._build_payload(model, messages, tools, max_tokens, stream=True, **kwargs)

        current_tool: Optional[Dict[str, Any]] = None
        collected_tools: List[ToolCall] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if not data_str:
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    if event_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool = {"id": block.get("id", ""), "name": block.get("name", ""), "arguments": ""}
                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield StreamEvent(type="text_delta", text_delta=delta.get("text", ""))
                        elif delta.get("type") == "input_json_delta" and current_tool is not None:
                            current_tool["arguments"] += delta.get("partial_json", "")
                    elif event_type == "content_block_stop":
                        if current_tool is not None:
                            try:
                                args = json.loads(current_tool["arguments"] or "{}")
                            except json.JSONDecodeError:
                                args = {"_raw": current_tool["arguments"]}
                            collected_tools.append(
                                ToolCall(id=current_tool["id"], name=current_tool["name"], arguments=args)
                            )
                            current_tool = None
                    elif event_type == "message_delta":
                        stop_reason = event.get("delta", {}).get("stop_reason")
                        if stop_reason:
                            yield StreamEvent(type="done", tool_calls=collected_tools, finish_reason=stop_reason)
                    elif event_type == "message_stop":
                        if not collected_tools:
                            yield StreamEvent(type="done", tool_calls=[], finish_reason="end_turn")
