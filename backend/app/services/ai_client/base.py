"""AI Provider 客户端的统一抽象：不同厂商/协议（OpenAI 兼容、Responses、Anthropic）通过各自的
适配器实现同一套接口，上层业务代码（模型管理测试连接、对话编辑 Agent）不用关心差异。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None


@dataclass
class StreamEvent:
    """流式增量事件：type 为 text_delta / tool_call / done"""

    type: str
    text_delta: str = ""
    reasoning_delta: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class AIClient(Protocol):
    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> ChatResult: ...

    async def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]: ...
