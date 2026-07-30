"""Atomic historical re-ask support without rewriting the raw event ledger."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_history_archive import ChatHistoryArchive
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.services.document_versions import content_checksum


class ChatReaskError(ValueError):
    pass


class ChatReaskConflictError(ChatReaskError):
    """The document changed after the requested history branch."""

    def __init__(self, current_checksum: str):
        super().__init__("此消息之后存在手动或其他对话修改，无法安全回退")
        self.current_checksum = current_checksum


@dataclass(frozen=True)
class ReaskActivation:
    archive_id: int
    source_message_id: int
    current_html: str


def _restore_html(db: Session, document: Document, session: ChatSession, target: ChatMessage) -> str:
    html_before = target.html_before
    if html_before is not None:
        return html_before

    following_ai = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.session_id == session.id,
            ChatMessage.role == MessageRole.ASSISTANT,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.id > target.id,
            ChatMessage.html_before.is_not(None),
        )
        .order_by(ChatMessage.id)
        .first()
    )
    if following_ai and following_ai.html_before is not None:
        return following_ai.html_before

    previous_ai = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.session_id == session.id,
            ChatMessage.role == MessageRole.ASSISTANT,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.id < target.id,
            ChatMessage.html_after.is_not(None),
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    if previous_ai and previous_ai.html_after is not None:
        return previous_ai.html_after
    raise ChatReaskError("该历史消息缺少可恢复的文档快照，无法安全回退")


def activate_reask(
    db: Session,
    *,
    document: Document,
    session: ChatSession,
    source_message_id: int,
    discard_document_changes: bool = False,
    expected_current_checksum: str | None = None,
) -> ReaskActivation:
    """Archive the active suffix and restore the document inside the caller transaction."""
    # The caller may have loaded a stale session before a compactor finishes.
    # Locking its durable coordination row makes archive and snapshot
    # invalidation atomic with respect to a concurrent context checkpoint.
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session.id)
        .with_for_update()
        .one()
    )
    target = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == source_message_id,
            ChatMessage.document_id == document.id,
            ChatMessage.session_id == session.id,
            ChatMessage.role == MessageRole.USER,
            ChatMessage.is_superseded.is_(False),
        )
        .first()
    )
    if target is None:
        raise ChatReaskError("未找到当前对话中可重新提问的消息")
    if session.context_start_message_id and target.id <= session.context_start_message_id:
        raise ChatReaskError("该历史消息已从当前上下文截断，无法从此重新提问")

    html_before = _restore_html(db, document, session, target)
    latest_change = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.session_id == session.id,
            ChatMessage.role == MessageRole.ASSISTANT,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.id >= target.id,
            ChatMessage.html_after.is_not(None),
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    expected_html = latest_change.html_after if latest_change and latest_change.html_after is not None else html_before
    if document.current_html != expected_html:
        current_checksum = content_checksum(document.current_html)
        if not discard_document_changes or expected_current_checksum != current_checksum:
            raise ChatReaskConflictError(current_checksum)

    archive = ChatHistoryArchive(session_id=session.id, source_message_id=target.id, reason="reask")
    db.add(archive)
    db.flush()
    now = datetime.now(timezone.utc)
    (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document.id,
            ChatMessage.session_id == session.id,
            ChatMessage.is_superseded.is_(False),
            ChatMessage.id >= target.id,
        )
        .update(
            {
                ChatMessage.is_superseded: True,
                ChatMessage.superseded_at: now,
                ChatMessage.history_archive_id: archive.id,
            },
            synchronize_session=False,
        )
    )
    # A snapshot which has already compacted this source message cannot be
    # reused. Earlier snapshots remain eligible and are proven by their hash.
    (
        db.query(ChatContextSnapshot)
        .filter(
            ChatContextSnapshot.session_id == session.id,
            ChatContextSnapshot.is_active.is_(True),
            ChatContextSnapshot.compacted_through_message_id >= target.id,
        )
        .update(
            {"is_active": False, "active_slot": None, "invalidation_reason": "reask"},
            synchronize_session=False,
        )
    )
    document.current_html = html_before
    return ReaskActivation(archive_id=archive.id, source_message_id=target.id, current_html=html_before)
