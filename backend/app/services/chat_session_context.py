"""Durable component and theme context scoped to one chat session."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.chat_session import ChatSessionTemplateAttachment, ChatSessionThemeContext
from app.models.gzh_theme_proposal import GzhThemeProposal, GzhThemeProposalStatus
from app.models.template_library import TemplateLibraryItem


MAX_SESSION_TEMPLATE_ATTACHMENTS = 6


class ChatSessionContextError(ValueError):
    pass


def _normalise_template_ids(template_ids: list[int]) -> list[int]:
    ordered = list(dict.fromkeys(int(item) for item in template_ids if int(item) > 0))
    if len(ordered) > MAX_SESSION_TEMPLATE_ATTACHMENTS:
        raise ChatSessionContextError(f"每个对话最多附加 {MAX_SESSION_TEMPLATE_ATTACHMENTS} 个模板")
    return ordered


def session_attached_templates(db: Session, session_id: int) -> list[TemplateLibraryItem]:
    return (
        db.query(TemplateLibraryItem)
        .join(
            ChatSessionTemplateAttachment,
            ChatSessionTemplateAttachment.template_id == TemplateLibraryItem.id,
        )
        .filter(ChatSessionTemplateAttachment.session_id == session_id)
        .order_by(ChatSessionTemplateAttachment.sort_order, ChatSessionTemplateAttachment.id)
        .all()
    )


def replace_session_attached_templates(
    db: Session,
    session_id: int,
    template_ids: list[int],
) -> list[TemplateLibraryItem]:
    ordered_ids = _normalise_template_ids(template_ids)
    templates = (
        db.query(TemplateLibraryItem)
        .filter(TemplateLibraryItem.id.in_(ordered_ids))
        .all()
        if ordered_ids
        else []
    )
    by_id = {item.id: item for item in templates}
    if any(template_id not in by_id for template_id in ordered_ids):
        raise ChatSessionContextError("附加的模板不存在或已被删除")
    db.query(ChatSessionTemplateAttachment).filter(
        ChatSessionTemplateAttachment.session_id == session_id
    ).delete(synchronize_session=False)
    db.add_all(
        ChatSessionTemplateAttachment(session_id=session_id, template_id=template_id, sort_order=index)
        for index, template_id in enumerate(ordered_ids)
    )
    db.flush()
    return [by_id[template_id] for template_id in ordered_ids]


def session_theme_proposal(db: Session, session_id: int) -> GzhThemeProposal | None:
    return (
        db.query(GzhThemeProposal)
        .join(ChatSessionThemeContext, ChatSessionThemeContext.gzh_theme_proposal_id == GzhThemeProposal.id)
        .filter(ChatSessionThemeContext.session_id == session_id)
        .one_or_none()
    )


def session_approved_theme_proposal(db: Session, session_id: int) -> GzhThemeProposal | None:
    """Return the session's approved proposal while its initial application is unfinished."""
    proposal = session_theme_proposal(db, session_id)
    return proposal if proposal and proposal.status == GzhThemeProposalStatus.APPROVED else None


def bind_session_theme_proposal(db: Session, session_id: int, proposal_id: str) -> GzhThemeProposal:
    proposal = db.get(GzhThemeProposal, proposal_id)
    if proposal is None:
        raise ChatSessionContextError("主题提案不存在")
    context = (
        db.query(ChatSessionThemeContext)
        .filter(ChatSessionThemeContext.session_id == session_id)
        .one_or_none()
    )
    if context is None:
        db.add(ChatSessionThemeContext(session_id=session_id, gzh_theme_proposal_id=proposal.id))
    else:
        context.gzh_theme_proposal_id = proposal.id
    db.flush()
    return proposal


def clear_session_theme_proposal(db: Session, session_id: int) -> bool:
    return bool(
        db.query(ChatSessionThemeContext)
        .filter(ChatSessionThemeContext.session_id == session_id)
        .delete(synchronize_session=False)
    )
