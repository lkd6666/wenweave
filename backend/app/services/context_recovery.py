"""Recover completed work from durable, public tool results after interruption."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_message import ChatMessage


def recovered_context_events(
    tools: list[dict[str, Any]], blocks: list[dict[str, Any]], content: str,
    canonical: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Prefer canonical pairs; supplement only results absent from that transcript.

    Display reasoning and unfinished argument previews are never model history.
    Exact model_input is recorded with each durable tool_result before publishing
    it to the browser, including image references and stored-output handles.
    """
    events = list(canonical or [])
    answered = {
        str(event.get("payload", {}).get("tool_call_id", ""))
        for event in events if event.get("kind") == "tool"
    }
    recovered: list[dict[str, Any]] = []
    for tool in tools:
        call_id = str(tool.get("id") or "")
        model_input = tool.get("model_input") or {}
        if not call_id or call_id in answered or tool.get("preparing"):
            continue
        # A recovery-generated error without model_input may mean execution
        # was interrupted. Describe that uncertainty instead of claiming success.
        if tool.get("status") == "running" or tool.get("result") is None:
            continue
        tool_content = model_input.get("content") if isinstance(model_input, dict) else None
        if not isinstance(tool_content, str) or not tool_content:
            tool_content = json.dumps({
                "historical_result": tool.get("result"),
                "activity": tool.get("activity"),
                "execution_status": tool.get("status"),
            }, ensure_ascii=False)
        name = str(tool.get("name") or "unknown")
        revision = ""
        try:
            parsed = json.loads(tool_content)
            if isinstance(parsed, dict):
                revision = str(parsed.get("revision") or parsed.get("current_revision") or "")
        except (ValueError, TypeError):
            pass
        recovered.extend([
            {"kind": "assistant", "payload": {"content": "", "tool_calls": [{
                "id": call_id, "name": name,
                "args": tool.get("arguments") if isinstance(tool.get("arguments"), dict) else {},
            }]}},
            {"kind": "tool", "document_revision": revision, "payload": {
                "tool_call_id": call_id, "name": name, "content": tool_content,
                "status": "error" if tool.get("status") == "error" else "success",
            }},
        ])
        answered.add(call_id)
    if recovered:
        events.extend(recovered)
    # Keep progress/next-step prose as well as the terminal interruption notice.
    # Reasoning blocks are deliberately excluded.
    progress = "\n\n".join(
        str(block.get("content") or "") for block in blocks
        if block.get("type") == "content" and block.get("content")
    )
    text = progress or content
    if content and content not in text:
        text = f"{text}\n\n{content}"
    existing_text = "\n\n".join(
        str(event.get("payload", {}).get("content") or "")
        for event in events if event.get("kind") == "assistant"
    )
    if text and text not in existing_text:
        events.append({"kind": "assistant", "payload": {"content": text}})
    return events


def persist_recovered_context(db: Session, message: ChatMessage, run_id: str) -> bool:
    """Populate a recovered message's provider ledger in the same transaction."""
    existing = db.query(ChatContextEvent).filter(ChatContextEvent.message_id == message.id).order_by(ChatContextEvent.ordinal).all()
    canonical = [{"kind": row.kind.value, "payload": row.payload, "document_revision": row.document_revision} for row in existing]
    events = recovered_context_events(message.tool_calls, message.turn_blocks, message.content, canonical)
    for ordinal, event in enumerate(events[len(existing):], start=max((row.ordinal for row in existing), default=-1) + 1):
        db.add(ChatContextEvent(
            document_id=message.document_id, session_id=message.session_id,
            message_id=message.id, run_id=run_id, ordinal=ordinal,
            kind=ContextEventKind(event["kind"]),
            payload_json=json.dumps(event["payload"], ensure_ascii=False),
            document_revision=event.get("document_revision", ""),
        ))
    return len(events) > len(existing)
