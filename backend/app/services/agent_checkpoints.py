"""Recover completed edits against the document snapshot owned by the run."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.models.chat_message import ChatMessage
from app.models.chat_user_question import ChatUserQuestion, ChatUserQuestionStatus
from app.models.document import Document
from app.models.document_version import DocumentVersionSource
from app.services.document_activity import touch_document, touch_group
from app.services.document_html import same_document_html
from app.services.document_versions import create_document_version
from app.services.html_workspace import HtmlWorkspace


def checkpoint_save_state(db: Session, run: AgentRun, document: Document, *, label: str) -> tuple[str, str, bool]:
    """Caller holds document then run locks; keep original HTML for undo."""
    request = db.get(ChatMessage, run.user_message_id)
    original = request.html_before if request else None
    if original is None:
        return "none", document.current_html, False
    candidate = str(getattr(run, "checkpoint_html", "") or "")
    persisted_baseline = getattr(run, "checkpoint_document_html", None)
    baseline = persisted_baseline if isinstance(persisted_baseline, str) else original
    waiting_candidate = False
    question = (
        db.query(ChatUserQuestion).filter(ChatUserQuestion.run_id == run.id)
        .order_by((ChatUserQuestion.status == ChatUserQuestionStatus.WAITING).desc(),
                  ChatUserQuestion.created_at.desc(), ChatUserQuestion.answered_at.desc(),
                  ChatUserQuestion.id.desc()).first()
    )
    if question is not None:
        context = ChatUserQuestion._decode(question.execution_context_json, {})
        if (question.status == ChatUserQuestionStatus.WAITING or persisted_baseline is None) and isinstance(context.get("document_html"), str):
            baseline = context["document_html"]
        if question.status == ChatUserQuestionStatus.WAITING and isinstance(context.get("current_html"), str):
            waiting_candidate = True
            candidate = context["current_html"]
            if context.get("source_revision") and context["source_revision"] != HtmlWorkspace.revision_for(candidate):
                return "conflict", document.current_html, False
    if baseline is None or (not candidate and not waiting_candidate and persisted_baseline is None):
        return "none", document.current_html, False
    if document.current_html != candidate and not same_document_html(baseline, document.current_html):
        return "conflict", document.current_html, False
    changed = candidate != original
    if document.current_html != candidate:
        document.current_html = candidate
        touch_document(document, run.user_id)
        if document.group:
            touch_group(document.group, run.user_id)
        create_document_version(db, document, run.user_id, DocumentVersionSource.AI, label)
    return "preserved" if changed else "none", document.current_html, changed
