from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class ChatUserQuestionStatus(str, enum.Enum):
    WAITING = "waiting"
    ANSWERED = "answered"
    CANCELLED = "cancelled"


class ChatUserQuestion(Base):
    """Durable human-in-the-loop pause for one Agent run.

    The serialized message state ends with the assistant's original tool call.
    Answering the question appends a ToolMessage with the same tool_call_id and
    resumes the graph without manufacturing a user chat message.
    """

    __tablename__ = "chat_user_questions"
    __table_args__ = (
        # A run may pause for more than one sequential question.  The tool
        # call itself remains unique so a replay cannot persist the same pause
        # twice.
        UniqueConstraint("run_id", "tool_call_id", name="uq_chat_user_questions_run_call"),
        UniqueConstraint("answer_client_request_id", name="uq_chat_user_questions_answer_request"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("ai_models.id", ondelete="RESTRICT"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ChatUserQuestionStatus] = mapped_column(
        Enum(ChatUserQuestionStatus), nullable=False, default=ChatUserQuestionStatus.WAITING
    )
    question_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    # Full provider-visible state, ending with the pending AI tool call.
    resume_messages_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    completed_context_events_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="[]")
    execution_context_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    timeline_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    answer_json: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="{}")
    answer_client_request_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    # Interaction refreshes the deadline. Nullable keeps an existing paused
    # question recoverable while the lightweight compatibility migration runs.
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @staticmethod
    def _decode(value: str, fallback: Any) -> Any:
        try:
            parsed = json.loads(value or "")
        except json.JSONDecodeError:
            return fallback
        return parsed if isinstance(parsed, type(fallback)) else fallback

    @property
    def question(self) -> dict[str, Any]:
        return self._decode(self.question_json, {})

    @property
    def answer(self) -> dict[str, Any]:
        return self._decode(self.answer_json, {})
