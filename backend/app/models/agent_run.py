from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, LONG_TEXT


class AgentRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AgentRun(Base):
    """一次可重连的 Agent 执行记录。

    实时事件保存在进程内以避免逐 token 写库；该表负责请求幂等、并发互斥和断线后的
    终态恢复。进程重启时未完成运行会被标记为失败，已完成工具修改仍由助手消息保存。
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "client_request_id", name="uq_agent_run_user_request"),
        Index("ix_agent_runs_document_status", "document_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_message_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    assistant_message_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    client_request_id: Mapped[str] = mapped_column(String(96), nullable=False)
    # Persist the request origin because the terminal audit record is often
    # written asynchronously after the initiating HTTP request has completed.
    origin_client_ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    origin_user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus), nullable=False, default=AgentRunStatus.PENDING
    )
    error_message: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    # The most recent successful write-tool result. It lets cancellation and
    # process-recovery paths preserve completed edits without waiting for a
    # final natural-language model response.
    checkpoint_html: Mapped[str] = mapped_column(LONG_TEXT, nullable=False, default="")
    # A run can be owned by exactly one live worker.  The lease protects
    # cross-worker SSE, cancellation and restart recovery from interpreting
    # another worker's in-process task as a failed run.
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_phase: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_sequence: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
