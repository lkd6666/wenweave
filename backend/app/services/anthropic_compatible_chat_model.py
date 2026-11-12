"""Accept beta context metadata returned in standard Anthropic streams."""
from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from pydantic import RootModel


class AnthropicCompatibleChatModel(ChatAnthropic):
    def _make_message_chunk_from_anthropic_event(
        self,
        event: Any,
        *,
        stream_usage: bool = True,
        coerce_content_to_string: bool,
        block_start_event: Any = None,
    ):
        context_management = getattr(event, "context_management", None)
        if event.type == "message_delta" and isinstance(context_management, dict):
            # Standard SDK events retain this beta field as a dict, while
            # LangChain expects an object exposing model_dump(). Copy the event
            # and preserve all metadata without changing the request protocol.
            event = event.model_copy(update={
                "context_management": RootModel[dict[str, Any]](context_management),
            })
        return super()._make_message_chunk_from_anthropic_event(
            event,
            stream_usage=stream_usage,
            coerce_content_to_string=coerce_content_to_string,
            block_start_event=block_start_event,
        )
