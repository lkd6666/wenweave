"""Session-scoped retrieval for context that has left the hot prompt."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.chat_context_event import ChatContextEvent
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage
from app.models.chat_tool_output import ChatToolOutput
from app.models.agent_run import AgentRun
from app.services.token_budget import estimate_tokens, truncate_to_tokens


class SessionHistoryError(ValueError):
    pass


def _event_text(event: ChatContextEvent) -> str:
    payload = event.payload
    return str(payload.get("content", ""))


class SessionHistoryReader:
    """Read only canonical session data visible after the context reset boundary."""

    def __init__(self, document_id: int, session_id: int):
        self.document_id = document_id
        self.session_id = session_id

    def _context_start(self, db: Session) -> int:
        session = db.get(ChatSession, self.session_id)
        if session is None or session.document_id != self.document_id:
            raise SessionHistoryError("当前会话不存在或无权访问")
        return int(session.context_start_message_id or 0)

    def _events(self, db: Session) -> list[ChatContextEvent]:
        start = self._context_start(db)
        query = (
            db.query(ChatContextEvent)
            # Orphaned legacy events are auditable but cannot be assigned to a
            # surviving branch.  Never make them retrievable by the model.
            .join(ChatMessage, ChatContextEvent.message_id == ChatMessage.id)
            .filter(
                ChatContextEvent.document_id == self.document_id,
                ChatContextEvent.session_id == self.session_id,
                ChatMessage.document_id == self.document_id,
                ChatMessage.session_id == self.session_id,
                ChatMessage.is_superseded.is_(False),
            )
        )
        if start:
            query = query.filter(ChatContextEvent.message_id > start)
        return query.order_by(ChatContextEvent.id).all()

    def search(self, db: Session, query: str, *, cursor: int = 0, limit: int = 8) -> dict[str, Any]:
        phrase = " ".join(str(query).lower().split())
        if not phrase:
            raise SessionHistoryError("请提供要检索的关键词")
        limit = max(1, min(20, int(limit)))
        offset = max(0, int(cursor))
        matches: list[dict[str, Any]] = []
        for event in self._events(db):
            content = _event_text(event)
            if phrase not in content.lower():
                continue
            matches.append(
                {
                    "reference": f"event:{event.id}",
                    "kind": event.kind.value,
                    "message_id": event.message_id,
                    "snippet": truncate_to_tokens(content, 180),
                }
            )
        output_query = (
            db.query(ChatToolOutput)
            .join(AgentRun, ChatToolOutput.run_id == AgentRun.id)
            .join(ChatMessage, AgentRun.user_message_id == ChatMessage.id)
            .filter(
                ChatToolOutput.document_id == self.document_id,
                ChatToolOutput.session_id == self.session_id,
                AgentRun.document_id == self.document_id,
                AgentRun.session_id == self.session_id,
                ChatMessage.is_superseded.is_(False),
            )
        )
        start = self._context_start(db)
        if start:
            output_query = output_query.filter(AgentRun.user_message_id > start)
        for output in output_query.order_by(ChatToolOutput.created_at).all():
            if phrase not in output.content.lower():
                continue
            matches.append(
                {
                    "reference": f"tool:{output.output_id}",
                    "kind": "tool_output",
                    "tool": output.tool_name,
                    "snippet": truncate_to_tokens(output.content, 180),
                }
            )
        page = matches[offset : offset + limit]
        return {
            "ok": True,
            "query": query,
            "results": page,
            "next_cursor": offset + limit if offset + limit < len(matches) else None,
            "total": len(matches),
        }

    def read(self, db: Session, reference: str, *, cursor: int = 0, max_tokens: int = 1_024) -> dict[str, Any]:
        max_tokens = max(128, min(20_000, int(max_tokens)))
        offset = max(0, int(cursor))
        if reference.startswith("event:"):
            try:
                event_id = int(reference.split(":", 1)[1])
            except ValueError as exc:
                raise SessionHistoryError("会话事件引用无效") from exc
            event = next((item for item in self._events(db) if item.id == event_id), None)
            if event is None:
                raise SessionHistoryError("会话事件不存在或已从当前上下文中截断")
            content = _event_text(event)
            return {
                "ok": True,
                "reference": reference,
                "kind": event.kind.value,
                "content": truncate_to_tokens(content, max_tokens),
                "truncated": estimate_tokens(content) > max_tokens,
            }
        if reference.startswith("tool:"):
            output_id = reference.split(":", 1)[1]
            output = db.get(ChatToolOutput, output_id)
            if output is None or output.document_id != self.document_id or output.session_id != self.session_id:
                raise SessionHistoryError("工具结果不存在或无权访问")
            start = self._context_start(db)
            run = db.get(AgentRun, output.run_id)
            user_message = db.get(ChatMessage, run.user_message_id) if run is not None else None
            if (
                run is None
                or run.document_id != self.document_id
                or run.session_id != self.session_id
                or user_message is None
                or user_message.document_id != self.document_id
                or user_message.session_id != self.session_id
                or user_message.is_superseded
            ):
                raise SessionHistoryError("工具结果属于已放弃的历史分支")
            if start and int(run.user_message_id or 0) <= start:
                raise SessionHistoryError("工具结果已从当前上下文中截断")
            # Character offsets are used only as a continuation cursor; token limiting
            # keeps the provider-visible page inside the current turn budget.
            content = output.content[offset:]
            page = truncate_to_tokens(content, max_tokens)
            next_offset = offset + len(page)
            return {
                "ok": True,
                "reference": reference,
                "kind": "tool_output",
                "tool": output.tool_name,
                "content": page,
                "next_cursor": next_offset if next_offset < len(output.content) else None,
                "truncated": next_offset < len(output.content),
            }
        raise SessionHistoryError("会话详情引用无效")
