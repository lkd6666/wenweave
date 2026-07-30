"""Document-scoped chat session helpers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession


def ensure_default_chat_session(db: Session, document_id: int) -> ChatSession:
    """Return an active session, creating the document's first one when needed."""
    session = (
        db.query(ChatSession)
        .filter(
            ChatSession.document_id == document_id,
            ChatSession.is_archived.is_(False),
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .first()
    )
    if session:
        return session

    session = ChatSession(document_id=document_id, title="新对话")
    db.add(session)
    db.flush()
    return session
