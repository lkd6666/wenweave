"""可取消、可重连的 HTML 编辑 Agent 接口。"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import AsyncIterator
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user
from app.api.sse import SSE_RESPONSE_HEADERS
from app.bootstrap import recover_expired_agent_runs
from app.core.config import get_settings
from app.core.security import create_scoped_token, decode_access_token
from app.db.session import SessionLocal, get_db
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_run_event import AgentRunEvent
from app.models.app_runtime_lock import AppRuntimeLock
from app.models.ai_model import AIModel
from app.models.ai_image_model import AIImageModel
from app.models.image_generation import GeneratedImageAsset, ImageGeneration
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_history_archive import ChatHistoryArchive
from app.models.chat_session import ChatSession, ChatSessionMemory
from app.models.chat_user_question import ChatUserQuestion, ChatUserQuestionStatus
from app.models.document import Document
from app.models.document_version import DocumentVersionSource
from app.models.template_library import TemplateLibraryItem
from app.models.user import User
from app.services.article_typography import get_or_create_typography_settings, typography_settings_payload
from app.models.model_call_record import ModelCallRecord, ModelCallSource
from app.models.operation_log import OperationLogStatus
from app.schemas.chat import (
    AgentRunRead,
    ChatContextPreviewRequest,
    ChatContextCompactRequest,
    ChatContextStatsRead,
    ChatMessageRead,
    ChatHistoryArchiveRead,
    ChatReaskActivationRead,
    ChatSendRequest,
    ChatUserQuestionActivityRead,
    ChatUserQuestionAnswerRequest,
    ChatUserQuestionRead,
    PendingChatUserQuestionRead,
    ChatSessionCreate,
    ChatSessionImageSettingsUpdate,
    ChatSessionRead,
    ChatSessionTemplateAttachmentsUpdate,
    ChatSessionUpdate,
)
from app.schemas.chat_images import ChatImageAttachmentRead
from app.services.agent_run_manager import TERMINAL_STATUSES, agent_run_manager
from app.services.agent_run_recovery import recover_interrupted_turn
from app.services.agent_context import AGENT_TOOL_SCHEMA_RESERVE_TOKENS, AgentContextBuilder, ContextBudgetError, ContextRecord, context_prefix_hash
from app.services.chat_agent import (
    HtmlEditSession,
    build_chat_model,
    build_compaction_model,
    build_agent_prompt_cache_key,
    article_typography_prompt,
    claim_thinking_capability_fallback_data,
    context_budget_prompt,
    restore_resume_messages,
    run_agent_loop,
)
from app.services.chat_sessions import ensure_default_chat_session
from app.services.chat_reask import ChatReaskConflictError, ChatReaskError, ReaskActivation, activate_reask
from app.services.chat_session_context import (
    ChatSessionContextError,
    bind_session_theme_proposal,
    clear_session_theme_proposal,
    replace_session_attached_templates,
    session_attached_templates,
    session_approved_theme_proposal,
    session_theme_proposal,
)
from app.services.document_activity import touch_document, touch_group
from app.services.document_access import accessible_documents_query, can_access_document
from app.services.document_versions import create_document_version
from app.services.document_history_workspace import DocumentHistoryWorkspace
from app.services.layout_reference import (
    LayoutReferenceError,
    clear_session_layout_reference,
    get_layout_reference,
    get_session_layout_reference,
    materialize_layout_reference,
    replace_session_layout_reference,
    session_layout_reference_agent_payload,
    session_layout_reference_summary,
)
from app.services.model_access import can_access_image_model, can_access_model
from app.services.model_call_accounting import ModelCallTracker
from app.services.tool_output_store import ToolOutputStore
from app.services.wechat_compliance import run_compliance_check
from app.services.gzh_theme import (
    GzhThemeError,
    consume_approved_proposal,
    mark_proposal_applied,
    proposal_theme_payload,
    reask_theme_proposal_id,
)
from app.services.operation_logs import append_operation_log, get_operation_request_id, get_operation_request_metadata
from app.services.runtime_diagnostics import log_process_memory


def _template_payload_from_models(templates: list[TemplateLibraryItem]) -> list[dict]:
    return [{"id": item.id, "name": item.name, "html": item.html} for item in templates]


def _agent_image_model(
    db: Session,
    user_id: int,
    requested_model_id: int | None,
) -> AIImageModel | None:
    """Resolve an Agent image model without exposing inaccessible providers."""
    from sqlalchemy.orm import joinedload as _joinedload

    actor = db.get(User, user_id)
    if actor is None:
        return None
    if requested_model_id is not None:
        requested = (
            db.query(AIImageModel)
            .options(_joinedload(AIImageModel.provider))
            .filter(AIImageModel.id == requested_model_id)
            .first()
        )
        if (
            requested is not None
            and can_access_image_model(actor, requested)
            and requested.provider.image_protocol
            and requested.provider.image_base_url
        ):
            return requested
    # Eager-load provider to avoid N+1 queries when checking image_protocol.
    candidates = (
        db.query(AIImageModel)
        .options(_joinedload(AIImageModel.provider))
        .order_by(AIImageModel.is_default.desc(), AIImageModel.id)
        .all()
    )
    return next(
        (
            model
            for model in candidates
            if can_access_image_model(actor, model)
            and model.provider.image_protocol
            and model.provider.image_base_url
        ),
        None,
    )


def _attached_template_payload(db: Session, template_ids: list[int]) -> list[dict]:
    ordered_ids = list(dict.fromkeys(int(item) for item in template_ids))
    if not ordered_ids:
        return []
    templates = db.query(TemplateLibraryItem).filter(TemplateLibraryItem.id.in_(ordered_ids)).all()
    by_id = {item.id: item for item in templates}
    if any(item not in by_id for item in ordered_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附加的模板不存在或已被删除")
    return _template_payload_from_models([by_id[template_id] for template_id in ordered_ids])


def _session_attached_template_payload(db: Session, session_id: int) -> list[dict]:
    return _template_payload_from_models(session_attached_templates(db, session_id))


def _attached_template_prompt(templates: list[dict]) -> str:
    if not templates:
        return ""
    return "\n\n当前会话已附加组件模板：" + "、".join(str(item["name"]) for item in templates) + "。组件源码将在 Agent 工具调用中按需读取。"


def _theme_reference_payload(proposal) -> dict | None:
    if proposal is None or proposal.status.value not in {"approved", "applied"}:
        return None
    return {
        "proposal_id": proposal.id,
        "theme_name": proposal.theme_name,
        "theme_markdown": proposal.theme_markdown,
        "apply_mode": proposal.apply_mode,
        "user_instructions": proposal.user_instructions,
        **proposal_theme_payload(proposal, include_html=True),
    }


def _theme_reference_prompt(theme_reference: dict | None) -> str:
    if not theme_reference:
        return ""
    return (
        f"\n\n当前会话主题参考：{theme_reference['theme_name']}（{theme_reference['apply_mode']}）。"
        "主题快照仅在用户要求校正或加强主题细节时按需读取。"
    )
from app.services.chat_images import (
    MAX_CHAT_IMAGE_BYTES,
    MAX_CHAT_IMAGES_PER_MESSAGE,
    ChatImageError,
    create_attachment,
    delete_attachment_object,
    duplicate_attachment,
    read_attachment_bytes,
    user_message_content,
)

router = APIRouter(prefix="/api/documents", tags=["chat"])
user_question_router = APIRouter(prefix="/api/chat-user-questions", tags=["chat"])
logger = logging.getLogger(__name__)

EXECUTING_RUN_STATUSES = {
    AgentRunStatus.PENDING,
    AgentRunStatus.RUNNING,
    AgentRunStatus.CANCELLING,
}
ACTIVE_RUN_STATUSES = {*EXECUTING_RUN_STATUSES, AgentRunStatus.WAITING_FOR_INPUT}
EDIT_TOOL_NAMES = {"apply_html_patch", "replace_document"}
settings = get_settings()
AGENT_EVENT_IDLE_TIMEOUT_SECONDS = settings.CHAT_AGENT_EVENT_IDLE_TIMEOUT_SECONDS
AGENT_MAX_RUNTIME_SECONDS = settings.CHAT_AGENT_MAX_RUNTIME_SECONDS
AGENT_TURN_FINALIZATION_TIMEOUT_SECONDS = settings.CHAT_AGENT_TURN_FINALIZATION_TIMEOUT_SECONDS
AGENT_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS = settings.CHAT_AGENT_MODEL_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS
CANCEL_GRACE_SECONDS = 8
FORCED_CANCELLATION_MESSAGE = "已停止本轮操作。模型未在短时间内响应停止请求，后续输出未被保存。"
CONTEXT_LIMIT_ERROR_PATTERN = re.compile(
    r"context(?:[_ -]?length)?|maximum context|input.*too (?:long|large)|too many tokens|token limit",
    re.IGNORECASE,
)
MODEL_CAPACITY_ERROR_PATTERN = re.compile(
    r"(?:\b429\b|\b503\b|rate.?limit|too many requests|overloaded|service(?:[_ ]is)? too busy|"
    r"service[_ ]unavailable|concurrency (?:limit|exceeded)|concurrent requests|account.*busy)",
    re.IGNORECASE,
)
CHAT_IMAGE_PREVIEW_SCOPE = "chat-image-preview"
CHAT_IMAGE_PREVIEW_TOKEN_MINUTES = 5
USER_QUESTION_TIMEOUT_CLIENT_REQUEST_PREFIX = "system-timeout:"
USER_QUESTION_TIMEOUT_RETRY_DELAY_SECONDS = 0.5
_user_question_timeout_tasks: dict[str, asyncio.Task[None]] = {}
USER_QUESTION_SNAPSHOT_INTERVAL_SECONDS = 1.0


def _is_context_limit_error(message: str) -> bool:
    return bool(CONTEXT_LIMIT_ERROR_PATTERN.search(message))


def _layout_reference_context_prompt(reference: dict | None) -> str:
    if not reference:
        return ""
    strength = str(reference.get("imitation_strength") or "structure")
    strength_label = {"style": "风格", "structure": "结构", "maximum": "最大还原"}.get(strength, "结构")
    return (
        "\n\n当前对话已绑定参考排版模板："
        f"{reference.get('title', '未命名参考文章')}（{reference.get('block_count', 0)} 个排版块，"
        f"{reference.get('image_assets', 0)} 个已授权素材，模仿强度：{strength_label}）。"
        "模板源码不进入上下文；Agent 可在本轮按需读取。"
    )


def _get_accessible_document(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if not document or not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return document


def _attachment_read(attachment: ChatImageAttachment, user: User) -> dict:
    token = create_scoped_token(
        str(user.id),
        CHAT_IMAGE_PREVIEW_SCOPE,
        {"document_id": attachment.document_id, "attachment_id": attachment.id},
        expires_in_minutes=CHAT_IMAGE_PREVIEW_TOKEN_MINUTES,
    )
    return ChatImageAttachmentRead(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size=attachment.size,
        preview_url=f"/api/documents/{attachment.document_id}/chat-images/{attachment.id}/content?token={token}",
    ).model_dump()


def _assistant_message_model_usage(db: Session, messages: list[ChatMessage]) -> dict[int, dict]:
    assistant_message_ids = [message.id for message in messages if message.role == MessageRole.ASSISTANT]
    if not assistant_message_ids:
        return {}

    rows = (
        db.query(
            AgentRun.assistant_message_id,
            ModelCallRecord.model_id,
            AIModel.display_name,
            ModelCallRecord.input_tokens,
            ModelCallRecord.output_tokens,
            ModelCallRecord.cache_read_tokens,
            ModelCallRecord.cache_write_tokens,
            ModelCallRecord.usage_reported,
        )
        .join(ModelCallRecord, ModelCallRecord.source_id == AgentRun.id)
        .outerjoin(AIModel, AIModel.id == ModelCallRecord.model_id)
        .filter(
            AgentRun.assistant_message_id.in_(assistant_message_ids),
            ModelCallRecord.source.in_(
                (
                    ModelCallSource.AGENT,
                    ModelCallSource.AGENT_CONTEXT_COMPACTION,
                    ModelCallSource.AGENT_RUNTIME_COMPACTION,
                )
            ),
        )
        .all()
    )
    usage_by_message: dict[int, dict] = {}
    for assistant_message_id, model_id, display_name, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, usage_reported in rows:
        if assistant_message_id is None:
            continue
        usage = usage_by_message.setdefault(
            int(assistant_message_id),
            {
                "models": {},
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "call_count": 0,
                "usage_reported": False,
            },
        )
        model = usage["models"].setdefault(
            int(model_id),
            {"name": display_name or f"模型 #{model_id}", "total_tokens": 0},
        )
        input_count = max(0, int(input_tokens or 0))
        output_count = max(0, int(output_tokens or 0))
        usage["input_tokens"] += input_count
        usage["output_tokens"] += output_count
        usage["cache_read_tokens"] += max(0, int(cache_read_tokens or 0))
        usage["cache_write_tokens"] += max(0, int(cache_write_tokens or 0))
        usage["call_count"] += 1
        usage["usage_reported"] = usage["usage_reported"] or bool(usage_reported)
        model["total_tokens"] += input_count + output_count

    return {
        message_id: {
            "model_names": [
                item["name"]
                for item in sorted(usage["models"].values(), key=lambda item: (-item["total_tokens"], item["name"]))
            ],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
            "cache_read_tokens": usage["cache_read_tokens"],
            "cache_write_tokens": usage["cache_write_tokens"],
            "cache_hit_rate": round(usage["cache_read_tokens"] / max(1, usage["input_tokens"]) * 100),
            "call_count": usage["call_count"],
            "usage_reported": usage["usage_reported"],
        }
        for message_id, usage in usage_by_message.items()
    }


def _message_read(message: ChatMessage, user: User, model_usage: dict | None = None) -> dict:
    payload = ChatMessageRead.model_validate(message).model_dump()
    payload["image_attachments"] = [_attachment_read(item, user) for item in message.image_attachments]
    payload["model_usage"] = model_usage
    return payload


def _pending_attachments(
    db: Session, document_id: int, user_id: int, attachment_ids: list[str], *, require_unbound: bool = True
) -> list[ChatImageAttachment]:
    if len(attachment_ids) > MAX_CHAT_IMAGES_PER_MESSAGE or len(set(attachment_ids)) != len(attachment_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="每条消息最多附加 5 张不同图片")
    if not attachment_ids:
        return []
    rows = db.query(ChatImageAttachment).filter(ChatImageAttachment.id.in_(attachment_ids)).all()
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(attachment_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="聊天图片不存在")
    ordered = [by_id[attachment_id] for attachment_id in attachment_ids]
    if any(row.document_id != document_id or row.uploader_id != user_id for row in ordered):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能使用其他用户上传的聊天图片")
    if require_unbound and any(row.message_id is not None for row in ordered):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="聊天图片已发送")
    return ordered


def _question_read(
    question: ChatUserQuestion | None,
    event_sequence: int | None = None,
) -> ChatUserQuestionRead | None:
    if question is None or question.status != ChatUserQuestionStatus.WAITING:
        return None
    payload = question.question
    options = payload.get("options") if isinstance(payload.get("options"), list) else []
    return ChatUserQuestionRead(
        id=question.id,
        run_id=question.run_id,
        question=str(payload.get("question") or ""),
        options=options,
        allow_multiple=bool(payload.get("allow_multiple")),
        include_style=bool(payload.get("include_style")),
        # MySQL returns TIMESTAMP/DATETIME values without tzinfo in this
        # deployment. Always serialize this deadline as UTC so browsers do
        # not interpret it as a local time and disable the answer controls
        # eight hours early in China Standard Time.
        timeout_at=_utc_question_deadline(question),
        inactivity_seconds=max(1, int(settings.CHAT_USER_QUESTION_INACTIVITY_SECONDS)),
        timeline=_json_dict(question.timeline_json),
        event_sequence=event_sequence,
    )


def _utc_datetime(value: datetime | None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    return resolved.replace(tzinfo=timezone.utc) if resolved.tzinfo is None else resolved.astimezone(timezone.utc)


def _pending_user_question_snapshot(user_id: int) -> list[dict]:
    """Return the durable, access-filtered question queue for one user."""
    snapshot_db = SessionLocal()
    try:
        actor = snapshot_db.get(User, user_id)
        if actor is None or not actor.is_active:
            return []
        query = (
            snapshot_db.query(ChatUserQuestion, AgentRun, Document)
            .join(AgentRun, AgentRun.id == ChatUserQuestion.run_id)
            .join(Document, Document.id == ChatUserQuestion.document_id)
            .filter(
                ChatUserQuestion.user_id == user_id,
                ChatUserQuestion.status == ChatUserQuestionStatus.WAITING,
                AgentRun.user_id == user_id,
                AgentRun.status == AgentRunStatus.WAITING_FOR_INPUT,
                AgentRun.document_id == ChatUserQuestion.document_id,
            )
        )
        rows = (
            accessible_documents_query(query, actor)
            .order_by(ChatUserQuestion.created_at, ChatUserQuestion.id)
            .all()
        )
        result: list[dict] = []
        for question, run, document in rows:
            question_payload = _question_read(question, int(run.event_sequence or 0))
            if question_payload is None:
                continue
            result.append(
                PendingChatUserQuestionRead(
                    document_id=document.id,
                    document_title=document.title,
                    session_id=question.session_id,
                    created_at=_utc_datetime(question.created_at),
                    question=question_payload,
                ).model_dump(mode="json")
            )
        return result
    finally:
        snapshot_db.close()


async def _pending_user_question_event_stream(user_id: int) -> AsyncIterator[dict]:
    previous_snapshot = ""
    while True:
        snapshot = await asyncio.to_thread(_pending_user_question_snapshot, user_id)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if encoded != previous_snapshot:
            previous_snapshot = encoded
            yield {"event": "pending_questions", "data": encoded}
        await asyncio.sleep(USER_QUESTION_SNAPSHOT_INTERVAL_SECONDS)


@user_question_router.get("/events")
def stream_pending_user_questions(
    current_user: User = Depends(get_current_user),
) -> EventSourceResponse:
    return EventSourceResponse(
        _pending_user_question_event_stream(current_user.id),
        ping=15,
        headers=SSE_RESPONSE_HEADERS,
    )


def _is_current_waiting_question_event(run_id: str, payload: dict) -> bool:
    """Avoid replaying a question that was already answered after a refresh.

    Agent events are intentionally retained for reconnects, but a client that
    reconnects after its answer was accepted starts at sequence zero. Replaying
    the old ``user_question`` event in that window made the answered panel
    reappear and exposed controls that could only return a 409. The question
    row is the durable authority for whether this particular event remains
    actionable.
    """
    question_id = str(payload.get("id") or "").strip()
    if not question_id:
        # Preserve malformed legacy events rather than hiding a recoverable
        # run from the user. New events always include an ID.
        return True
    db = SessionLocal()
    try:
        question = db.get(ChatUserQuestion, question_id)
        run = db.get(AgentRun, run_id)
        return bool(
            question
            and run
            and question.run_id == run_id
            and question.status == ChatUserQuestionStatus.WAITING
            and run.status == AgentRunStatus.WAITING_FOR_INPUT
        )
    finally:
        db.close()


def _json_dict(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_read(
    run: AgentRun,
    reask_activation: ReaskActivation | None = None,
    user_question: ChatUserQuestion | None = None,
) -> AgentRunRead:
    return AgentRunRead(
        run_id=run.id,
        session_id=run.session_id,
        status=run.status,
        user_message_id=run.user_message_id,
        assistant_message_id=run.assistant_message_id,
        error_message=run.error_message,
        reask_activation=(
            ChatReaskActivationRead(
                archive_id=reask_activation.archive_id,
                source_message_id=reask_activation.source_message_id,
                current_html=reask_activation.current_html,
            )
            if reask_activation
            else None
        ),
        user_question=_question_read(user_question, int(run.event_sequence or 0)),
    )


def _run_lease_expired(run: AgentRun) -> bool:
    if not run.owner_id or run.lease_expires_at is None:
        return True
    lease_expires_at = run.lease_expires_at
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
    return lease_expires_at <= datetime.now(timezone.utc)


def _merge_runtime_context_stats(prepared_stats: dict, event_data: dict) -> dict:
    """Attach per-turn telemetry without replacing the next-request budget."""
    def metric(name: str) -> int:
        value = event_data.get(name)
        return value if isinstance(value, int) else 0

    runtime_state = str(event_data.get("state", ""))
    merged = {
        **prepared_stats,
        "runtime_context_state": runtime_state,
        **({"input_budget_tokens": metric("input_budget_tokens")} if metric("input_budget_tokens") else {}),
        **({"compaction_location": str(event_data["location"])} if event_data.get("location") else {}),
    }
    if runtime_state == "measured":
        return {
            **merged,
            "runtime_input_tokens": metric("used_tokens"),
            "last_model_output_tokens": metric("last_turn_output_tokens"),
            "last_model_cached_input_tokens": metric("cached_input_tokens"),
        }
    if runtime_state == "in_run_compacted":
        return {
            **merged,
            "runtime_input_tokens": metric("used_tokens"),
            "runtime_original_tokens": metric("run_original_tokens"),
            "runtime_digested_cycles": metric("run_digested_cycles"),
            "runtime_dropped_cycles": metric("run_dropped_cycles"),
            "run_summarized_cycles": metric("run_summarized_cycles"),
            "runtime_summary_tokens": metric("runtime_summary_tokens"),
        }
    if runtime_state == "streaming":
        return {
            **merged,
            "runtime_input_tokens": metric("used_tokens"),
            "runtime_projected_tokens": metric("runtime_projected_tokens"),
            "runtime_visible_output_tokens": metric("runtime_visible_output_tokens"),
            "runtime_reasoning_tokens": metric("runtime_reasoning_tokens"),
            "runtime_tool_argument_tokens": metric("runtime_tool_argument_tokens"),
        }
    if runtime_state == "tool_outputs_stored":
        return {
            **merged,
            "effective_tool_preview_tokens": metric("effective_tool_preview_tokens"),
            "stored_tool_output_count": metric("stored_tool_output_count"),
            "stored_tool_output_bytes": metric("stored_tool_output_bytes"),
            "stored_tool_output_tokens": metric("stored_tool_output_tokens"),
            "tool_output_retention_days": metric("tool_output_retention_days"),
        }
    return merged


def _persist_context_events(
    db: Session,
    *,
    document_id: int,
    session_id: int,
    message_id: int,
    run_id: str | None,
    events: list[dict] | None,
    fallback_content: str,
) -> None:
    """Persist only provider-legal event pairs; UI reasoning never enters here."""
    rows = events or []
    if not rows:
        rows = [{"kind": ContextEventKind.ASSISTANT.value, "payload": {"content": fallback_content}}]
    for ordinal, event in enumerate(rows):
        kind = str(event.get("kind", ""))
        if kind not in {item.value for item in ContextEventKind}:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        db.add(
            ChatContextEvent(
                document_id=document_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message_id,
                ordinal=ordinal,
                kind=ContextEventKind(kind),
                payload_json=json.dumps(payload, ensure_ascii=False),
                document_revision=str(event.get("document_revision", "")),
            )
        )


def _runtime_summary_memory(summary: str) -> dict | None:
    """Adapt the validated run-level work state to the durable snapshot schema."""
    try:
        value = json.loads(summary)
    except (TypeError, json.JSONDecodeError):
        return None
    required = ("objective", "constraints", "decisions", "completed", "active_work", "blockers", "next_steps", "source_refs")
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) for key in required):
        return None

    def items(*keys: str) -> list[str]:
        return [str(value[key]).strip() for key in keys if str(value[key]).strip() and str(value[key]).strip() not in {"无", "none", "None"}]

    return {
        "objective": str(value["objective"]).strip(),
        "important_details": items("constraints", "decisions"),
        "user_preferences": [],
        "completed_intents": items("completed"),
        "active_work": items("active_work"),
        "pending_tasks": items("next_steps"),
        "blocked": items("blockers"),
        "next_move": items("next_steps"),
        "relevant_files": [],
        "source_refs": items("source_refs"),
        "narrative": str(value["completed"]).strip(),
    }


def _persist_runtime_compaction_snapshot(
    db: Session,
    *,
    session_id: int,
    assistant_message_id: int,
    runtime_compaction: dict | None,
    model_id: int,
    input_budget_tokens: int,
) -> None:
    """Commit a run-level summary only after its source events are durable.

    The source summary includes the current durable memory, hot prefix and every
    collapsed tool cycle. If the input had to be abbreviated for the compactor,
    it remains an in-run projection only and is deliberately not promoted.
    """
    if not isinstance(runtime_compaction, dict) or not runtime_compaction.get("durable_snapshot"):
        return
    summary = _runtime_summary_memory(str(runtime_compaction.get("summary", "")))
    target_cycles = int(runtime_compaction.get("summarized_cycles", 0) or 0)
    if summary is None or target_cycles <= 0:
        return
    events = (
        db.query(ChatContextEvent)
        .filter(ChatContextEvent.session_id == session_id, ChatContextEvent.message_id == assistant_message_id)
        .order_by(ChatContextEvent.id)
        .all()
    )
    index = 0
    completed_cycles = 0
    cutoff_event_id = 0
    while index < len(events) and completed_cycles < target_cycles:
        assistant_event = events[index]
        if assistant_event.kind != ContextEventKind.ASSISTANT:
            break
        calls = assistant_event.payload.get("tool_calls", [])
        calls = calls if isinstance(calls, list) else []
        call_ids = {str(call.get("id", "")) for call in calls if isinstance(call, dict) and call.get("id")}
        if not call_ids:
            break
        cursor = index + 1
        answered: set[str] = set()
        while cursor < len(events) and events[cursor].kind == ContextEventKind.TOOL:
            call_id = str(events[cursor].payload.get("tool_call_id", ""))
            if call_id in call_ids:
                answered.add(call_id)
            cursor += 1
        if answered != call_ids or cursor == index + 1:
            break
        completed_cycles += 1
        cutoff_event_id = int(events[cursor - 1].id)
        index = cursor
    if completed_cycles < target_cycles or not cutoff_event_id:
        return

    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id)
        .with_for_update()
        .one_or_none()
    )
    if session is None:
        return
    active_snapshot = (
        db.query(ChatContextSnapshot)
        .filter(ChatContextSnapshot.session_id == session_id, ChatContextSnapshot.is_active.is_(True))
        .order_by(ChatContextSnapshot.id.desc())
        .first()
    )
    source_start_event_id = int(active_snapshot.source_start_event_id or 0) if active_snapshot else 0
    if not source_start_event_id:
        first_event_query = db.query(ChatContextEvent.id).filter(ChatContextEvent.session_id == session_id)
        if session.context_start_message_id:
            first_event_query = first_event_query.filter(
                or_(
                    ChatContextEvent.message_id.is_(None),
                    ChatContextEvent.message_id > session.context_start_message_id,
                )
            )
        source_start_event_id = int(first_event_query.order_by(ChatContextEvent.id).limit(1).scalar() or 0)
    if not source_start_event_id:
        return
    source_events = (
        db.query(ChatContextEvent)
        .join(ChatMessage, ChatContextEvent.message_id == ChatMessage.id)
        .filter(
            ChatContextEvent.session_id == session_id,
            ChatMessage.is_superseded.is_(False),
        )
        .order_by(ChatContextEvent.id)
        .all()
    )
    if session.context_start_message_id:
        source_events = [event for event in source_events if (event.message_id or 0) > session.context_start_message_id]
    source_count = sum(1 for event in source_events if event.id <= cutoff_event_id)
    if source_count <= 0:
        return
    source_records = [
        ContextRecord(
            id=event.id,
            message_id=event.message_id,
            kind=event.kind.value if isinstance(event.kind, ContextEventKind) else str(event.kind),
            payload=event.payload,
            document_revision=event.document_revision,
            is_legacy=event.is_legacy,
        )
        for event in source_events
    ]
    db.query(ChatContextSnapshot).filter(
        ChatContextSnapshot.session_id == session_id,
        ChatContextSnapshot.is_active.is_(True),
    ).update(
        {"is_active": False, "active_slot": None, "invalidation_reason": "replaced"},
        synchronize_session=False,
    )
    db.add(
        ChatContextSnapshot(
            session_id=session_id,
            source_start_event_id=source_start_event_id,
            compacted_through_event_id=cutoff_event_id,
            compacted_through_message_id=assistant_message_id,
            retained_from_event_id=cutoff_event_id + 1,
            summary_json=json.dumps(summary, ensure_ascii=False),
            strategy="agentic",
            trigger="run_automatic",
            model_id=model_id,
            input_budget_tokens=max(0, int(input_budget_tokens)),
            source_event_count=source_count,
            source_prefix_hash=context_prefix_hash(source_records, source_count),
            context_generation=int(session.context_generation or 0),
            is_active=True,
            active_slot=1,
        )
    )


def _active_run_for_document(db: Session, document_id: int) -> AgentRun | None:
    return (
        db.query(AgentRun)
        .filter(AgentRun.document_id == document_id, AgentRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(AgentRun.created_at.desc())
        .first()
    )


def _agent_start_cutoff(db: Session) -> datetime:
    """Build the rate-limit window with the same clock that writes runs.

    ``AgentRun.created_at`` is populated by the database's ``CURRENT_TIMESTAMP``.
    Comparing it to an application UTC value misclassifies old rows when the
    database session uses a local timezone and returns naive datetimes.
    """
    database_now = db.query(func.now()).scalar()
    if isinstance(database_now, datetime):
        return database_now - timedelta(minutes=1)
    logger.warning("agent_start_rate_limit_database_clock_unavailable")
    return datetime.now(timezone.utc) - timedelta(minutes=1)


def _require_agent_capacity(db: Session, user_id: int) -> None:
    """Shared admission gate, serialized across documents and workers."""
    gate = db.query(AppRuntimeLock).filter(AppRuntimeLock.name == "agent-admission").with_for_update().first()
    if gate is None:
        # A fresh deployment creates this during bootstrap. Keep a defensive
        # error instead of permitting an unbounded race if bootstrap was
        # interrupted midway.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Agent 准入服务正在初始化")
    active_query = db.query(AgentRun).filter(AgentRun.status.in_(EXECUTING_RUN_STATUSES))
    if active_query.count() >= max(1, settings.CHAT_AGENT_MAX_CONCURRENT_RUNS):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Agent 当前繁忙，请稍后重试",
            headers={"Retry-After": "5"},
        )
    if active_query.filter(AgentRun.user_id == user_id).count() >= max(1, settings.CHAT_AGENT_MAX_CONCURRENT_RUNS_PER_USER):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="你已有过多 Agent 正在执行，请等待完成后再试",
            headers={"Retry-After": "5"},
        )
    one_minute_ago = _agent_start_cutoff(db)
    if (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id, AgentRun.created_at >= one_minute_ago)
        .count()
        >= max(1, settings.CHAT_AGENT_STARTS_PER_MINUTE)
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Agent 启动过于频繁，请稍后再试",
            headers={"Retry-After": "60"},
        )


def _require_idle_document(db: Session, document_id: int) -> None:
    if _active_run_for_document(db, document_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前推文有正在执行的 Agent，完成或停止后才能管理对话")


def _get_chat_session(
    db: Session, document_id: int, session_id: int, *, allow_archived: bool = True
) -> ChatSession:
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.document_id == document_id)
        .first()
    )
    if not session or (session.is_archived and not allow_archived):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对话不存在或已归档")
    return session


def _default_chat_session(db: Session, document_id: int) -> ChatSession:
    session = ensure_default_chat_session(db, document_id)
    db.commit()
    db.refresh(session)
    return session


def _session_message_query(db: Session, session: ChatSession, *, include_hidden: bool = False):
    query = db.query(ChatMessage).filter(
        ChatMessage.document_id == session.document_id,
        ChatMessage.session_id == session.id,
        ChatMessage.is_superseded.is_(False),
    )
    if not include_hidden and session.context_start_message_id > 0:
        query = query.filter(ChatMessage.id > session.context_start_message_id)
    return query


def _parse_json_list(value: str) -> list[dict]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _session_read(db: Session, session: ChatSession) -> dict:
    total = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.document_id == session.document_id,
            ChatMessage.session_id == session.id,
            ChatMessage.is_superseded.is_(False),
        )
        .count()
    )
    hidden = 0
    if session.context_start_message_id > 0:
        hidden = (
            db.query(ChatMessage.id)
            .filter(
                ChatMessage.document_id == session.document_id,
                ChatMessage.session_id == session.id,
                ChatMessage.is_superseded.is_(False),
                ChatMessage.id <= session.context_start_message_id,
            )
            .count()
        )
    attached_templates = session_attached_templates(db, session.id)
    theme_proposal = session_theme_proposal(db, session.id)
    return {
        "id": session.id,
        "title": session.title,
        "is_archived": session.is_archived,
        "context_start_message_id": session.context_start_message_id,
        "visible_message_count": total - hidden,
        "hidden_message_count": hidden,
        "layout_reference": session_layout_reference_summary(get_session_layout_reference(db, session.id)),
        "attached_templates": [
            {
                "id": item.id,
                "name": item.name,
                "category_id": item.category_id,
                "source_type": item.source_type.value,
                "html": item.html,
                "image_warnings": _parse_json_list(item.image_warnings_json),
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in attached_templates
        ],
        "theme_context": (
            {
                "proposal_id": theme_proposal.id,
                "theme_key": theme_proposal.theme_key,
                "theme_name": theme_proposal.theme_name,
                "apply_mode": theme_proposal.apply_mode,
                "status": theme_proposal.status.value,
            }
            if theme_proposal
            else None
        ),
        "image_model_id": session.image_model_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _settle_terminal_timeline(tool_calls: list[dict], turn_blocks: list[dict]) -> bool:
    """Ensure a persisted assistant message never retains a live tool state."""
    changed = False

    def settle_tool(tool: dict) -> None:
        nonlocal changed
        if tool.get("status") not in {"running", "waiting"}:
            return
        tool["status"] = "error"
        if not tool.get("result"):
            tool["result"] = (
                "模型未完成工具参数生成，工具尚未执行。"
                if tool.get("preparing")
                else "本轮 Agent 已结束，未收到该工具的执行结果。"
            )
        tool["preparing"] = False
        changed = True

    for tool in tool_calls:
        if isinstance(tool, dict):
            settle_tool(tool)
    for block in turn_blocks:
        if not isinstance(block, dict):
            continue
        content = block.get("content")
        if not isinstance(content, str):
            block["content"] = "" if content is None else str(content)
            changed = True
        if block.get("state") == "active":
            block["state"] = "done"
            block.pop("_started_at", None)
            changed = True
        tool = block.get("tool")
        if isinstance(tool, dict):
            settle_tool(tool)
    return changed


def _user_question_resolution_presentation(answer: dict | None) -> tuple[str, dict]:
    """Return the user-facing timeline state for a resolved ask_user call."""
    action = str((answer or {}).get("action") or "")
    if action == "cancelled":
        return (
            "本轮操作已停止，未继续等待用户回答。",
            {"kind": "question", "summary": "本轮已停止"},
        )
    if action == "no_response":
        return (
            "用户在规定时间内未回复，已自动跳过本次确认并继续处理排版。",
            {"kind": "question", "summary": "用户未回复，已自动继续"},
        )
    if action == "skipped":
        return (
            "用户跳过了本次确认，继续处理排版。",
            {"kind": "question", "summary": "用户已跳过确认"},
        )
    return (
        "已收到用户回答，继续处理排版。",
        {"kind": "question", "summary": "已收到用户回答"},
    )


def _settle_user_question_timeline(
    tool_calls: list[dict],
    turn_blocks: list[dict],
    tool_call_id: str,
    answer: dict | None = None,
) -> str | None:
    """Mark a paused ask_user call as resolved and return its timeline ID.

    Before stable provider IDs were exposed to the timeline, a resumed run
    used a transient ``tool-0-0`` ID. The fallback keeps those already-paused
    runs truthful while new calls match their provider ``tool_call_id``.
    """
    exact_ids = [
        str(tool.get("id") or "")
        for tool in [
            *[item for item in tool_calls if isinstance(item, dict)],
            *[
                block.get("tool")
                for block in turn_blocks
                if isinstance(block, dict) and isinstance(block.get("tool"), dict)
            ],
        ]
        if tool.get("name") == "ask_user" and str(tool.get("id") or "") == tool_call_id
    ]
    timeline_tool_id = next(iter(exact_ids), "")
    if not timeline_tool_id:
        legacy_candidates = [
            tool
            for tool in [
                *[item for item in tool_calls if isinstance(item, dict)],
                *[
                    block.get("tool")
                    for block in turn_blocks
                    if isinstance(block, dict) and isinstance(block.get("tool"), dict)
                ],
            ]
            if tool.get("name") == "ask_user" and tool.get("status") in {"running", "waiting"}
        ]
        timeline_tool_id = str(legacy_candidates[-1].get("id") or "") if legacy_candidates else ""
    if not timeline_tool_id:
        return None
    result, activity = _user_question_resolution_presentation(answer)

    def settle_tool(tool: dict) -> None:
        if tool.get("id") != timeline_tool_id or tool.get("name") != "ask_user":
            return
        tool["status"] = "success"
        tool["preparing"] = False
        tool["result"] = result
        tool["activity"] = activity
        changed = True

    for tool in tool_calls:
        if isinstance(tool, dict):
            settle_tool(tool)
    for block in turn_blocks:
        if isinstance(block, dict) and isinstance(block.get("tool"), dict):
            settle_tool(block["tool"])
    return timeline_tool_id


def _preserve_retried_tool_previews(
    checkpoint_tools: list[dict],
    checkpoint_blocks: list[dict],
    current_tools: list[dict],
    current_blocks: list[dict],
    retry_data: dict,
) -> tuple[list[dict], list[dict], list[str]]:
    """Retain interrupted parameter generation as a truthful timeline entry.

    A provider retry must discard incomplete model content so it cannot be
    mistaken for a completed response. A pending tool call is different: it is
    useful operational evidence, especially for large HTML patches. Preserve
    it as ``interrupted`` with a new display ID, while the retried request is
    free to reuse the provider's original call ID.
    """
    baseline_ids = {
        str(tool.get("id") or "")
        for tool in checkpoint_tools
        if isinstance(tool, dict) and tool.get("id")
    }
    retry_attempt = max(1, int(retry_data.get("attempt") or 1))
    suffix = f":retry-{retry_attempt}"
    interrupted_by_source_id: dict[str, dict] = {}

    for tool in current_tools:
        if not isinstance(tool, dict):
            continue
        source_id = str(tool.get("id") or "")
        if (
            not source_id
            or source_id in baseline_ids
            or tool.get("status") != "running"
            or not tool.get("preparing")
        ):
            continue
        interrupted = copy.deepcopy(tool)
        interrupted["id"] = f"{source_id}{suffix}"
        interrupted["status"] = "interrupted"
        interrupted["preparing"] = False
        interrupted["result"] = "本次工具参数生成被模型重试中断，尚未执行任何修改。"
        interrupted["activity"] = {
            "kind": "retry",
            "summary": "参数生成中断，正在重新请求模型",
            "details": {"retry_reason": str(retry_data.get("reason") or "unknown")},
        }
        interrupted_by_source_id[source_id] = interrupted

    if not interrupted_by_source_id:
        return copy.deepcopy(checkpoint_tools), copy.deepcopy(checkpoint_blocks), []

    next_tools = [*copy.deepcopy(checkpoint_tools), *interrupted_by_source_id.values()]
    next_blocks = copy.deepcopy(checkpoint_blocks)
    block_tool_ids: set[str] = set()
    for block in current_blocks:
        if not isinstance(block, dict) or block.get("type") != "tool":
            continue
        source_tool = block.get("tool")
        if not isinstance(source_tool, dict):
            continue
        source_id = str(source_tool.get("id") or "")
        interrupted = interrupted_by_source_id.get(source_id)
        if not interrupted:
            continue
        copied_block = copy.deepcopy(block)
        copied_block["id"] = f"{str(block.get('id') or f'block-{source_id}')}{suffix}"
        copied_block["state"] = "done"
        copied_block["content"] = str(copied_block.get("content") or "")
        copied_block["tool"] = interrupted
        next_blocks.append(copied_block)
        block_tool_ids.add(str(interrupted["id"]))

    for source_id, interrupted in interrupted_by_source_id.items():
        if str(interrupted["id"]) in block_tool_ids:
            continue
        next_blocks.append(
            {
                "id": f"block-{source_id}{suffix}",
                "type": "tool",
                "state": "done",
                "content": "",
                "tool": interrupted,
            }
        )
    return next_tools, next_blocks, [str(item["id"]) for item in interrupted_by_source_id.values()]


def _unresolved_edit_failure(tool_calls: list[dict]) -> tuple[str, str] | None:
    """Return a truthful terminal outcome when the final edit attempt failed."""
    latest_failure = -1
    latest_success = -1
    for index, tool in enumerate(tool_calls):
        if not isinstance(tool, dict) or tool.get("name") not in EDIT_TOOL_NAMES:
            continue
        if tool.get("status") == "success":
            latest_success = index
        elif tool.get("status") == "error":
            latest_failure = index

    if latest_failure < 0 or latest_success > latest_failure:
        return None
    if latest_success >= 0:
        return (
            "本轮排版部分完成，已保留成功修改；最后一项排版补丁未完成，请根据上方错误重试。",
            "最后一项排版补丁未完成",
        )
    return (
        "本轮排版未完成：排版补丁未成功写入文档，请根据上方错误调整后重试。",
        "排版补丁未成功写入文档",
    )


def _settle_persisted_assistant_message(message: ChatMessage) -> bool:
    tool_calls = message.tool_calls
    turn_blocks = message.turn_blocks
    if not _settle_terminal_timeline(tool_calls, turn_blocks):
        return False
    message.tool_calls_json = json.dumps(tool_calls, ensure_ascii=False)
    message.turn_blocks_json = json.dumps(turn_blocks, ensure_ascii=False)
    return True


def _persist_restart_failure(db: Session, run: AgentRun, document: Document) -> str:
    """Finish an abandoned run while retaining its durable edit candidate."""
    if run.assistant_message_id:
        message = db.get(ChatMessage, run.assistant_message_id)
        if message and message.html_after:
            return "preserved"
        request_message = db.get(ChatMessage, run.user_message_id)
        checkpoint = str(getattr(run, "checkpoint_html", "") or "")
        if checkpoint and request_message and document.current_html != request_message.html_before:
            return "conflict"
        return "unavailable" if checkpoint else "none"

    locked_document = (
        db.query(Document)
        .filter(Document.id == document.id)
        .with_for_update()
        .first()
    ) or document
    save_state, report_html, html_changed = _checkpoint_save_state(
        db,
        run,
        locked_document,
        label="AI 编辑（服务恢复）",
    )
    if save_state == "preserved":
        content = "服务已重启，未完成的 Agent 已停止；已保留已完成的排版修改。"
    elif save_state == "conflict":
        content = "服务已重启，未完成的 Agent 已停止；文档已被其他修改更新，候选排版未自动覆盖。"
    else:
        content = run.error_message or "服务已重启，未完成的 Agent 已停止；请重新执行本轮操作"
    request_message = db.get(ChatMessage, run.user_message_id)
    events = (
        db.query(AgentRunEvent)
        .filter(AgentRunEvent.run_id == run.id)
        .order_by(AgentRunEvent.sequence)
        .all()
    )
    recovered_turn = recover_interrupted_turn(events, content)
    assistant_message = ChatMessage(
        document_id=locked_document.id,
        session_id=run.session_id,
        role=MessageRole.ASSISTANT,
        content=recovered_turn.content,
        tool_calls_json=json.dumps(recovered_turn.tool_calls, ensure_ascii=False),
        reasoning_trace_json=json.dumps(recovered_turn.reasoning_trace, ensure_ascii=False),
        turn_blocks_json=json.dumps(recovered_turn.turn_blocks, ensure_ascii=False),
        html_before=request_message.html_before if request_message else None,
        html_after=report_html if html_changed else None,
    )
    db.add(assistant_message)
    db.flush()
    run.assistant_message_id = assistant_message.id
    run.status = AgentRunStatus.FAILED
    run.error_message = content
    run.finished_at = run.finished_at or datetime.now(timezone.utc)
    append_operation_log(
        db,
        actor=db.get(User, run.user_id),
        action="chat.run",
        resource_type="chat_run",
        resource_id=run.id,
        resource_name=locked_document.title,
        document_id=locked_document.id,
        session_id=run.session_id,
        status=OperationLogStatus.FAILED,
        summary="AI 对话执行失败",
        error_summary="服务恢复时终止未完成的 AI 对话",
        details={"document_changed": html_changed, "recovered_after_restart": True},
        client_ip=run.origin_client_ip,
        user_agent=run.origin_user_agent,
    )
    return save_state


@router.post("/{document_id}/chat-images", response_model=ChatImageAttachmentRead, status_code=status.HTTP_201_CREATED)
async def upload_chat_image(
    document_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    attachment: ChatImageAttachment | None = None
    committed = False
    try:
        data = await file.read(MAX_CHAT_IMAGE_BYTES + 1)
        attachment = create_attachment(
            db,
            document_id=document_id,
            uploader_id=current_user.id,
            data=data,
            filename=file.filename or "image",
        )
        db.commit()
        committed = True
        db.refresh(attachment)
        return _attachment_read(attachment, current_user)
    except ChatImageError as exc:
        db.rollback()
        if attachment is not None and not committed:
            try:
                delete_attachment_object(db, attachment)
            except ChatImageError:
                logger.exception("Unable to compensate failed chat image upload %s", attachment.id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        if attachment is not None and not committed:
            try:
                delete_attachment_object(db, attachment)
            except ChatImageError:
                logger.exception("Unable to compensate failed chat image upload %s", attachment.id)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="聊天图片保存失败，请稍后重试") from exc
    finally:
        await file.close()


@router.post(
    "/{document_id}/chat-images/{attachment_id}/duplicate",
    response_model=ChatImageAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_chat_image(
    document_id: int,
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Restore a sent image as a new draft attachment for a historical re-ask."""
    _get_accessible_document(db, document_id, current_user)
    source = (
        db.query(ChatImageAttachment)
        .filter(ChatImageAttachment.id == attachment_id)
        .with_for_update()
        .one_or_none()
    )
    if source is None or source.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="聊天图片不存在")
    if source.message_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅可重新附加已发送的聊天图片")
    try:
        duplicate = duplicate_attachment(db, source=source, uploader_id=current_user.id)
        db.commit()
        db.refresh(duplicate)
        return _attachment_read(duplicate, current_user)
    except ChatImageError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Unable to duplicate chat image %s", attachment_id)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="聊天图片恢复失败，请稍后重试") from exc


@router.delete(
    "/{document_id}/chat-images/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_chat_image(
    document_id: int,
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    _get_accessible_document(db, document_id, current_user)
    attachment = (
        db.query(ChatImageAttachment)
        .filter(ChatImageAttachment.id == attachment_id)
        .with_for_update()
        .one_or_none()
    )
    if not attachment or attachment.document_id != document_id or attachment.uploader_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="聊天图片不存在")
    if attachment.message_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已发送的聊天图片不能删除")
    try:
        delete_attachment_object(db, attachment)
    except ChatImageError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    try:
        db.delete(attachment)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="聊天图片删除状态保存失败，请稍后重试") from exc


@router.get("/{document_id}/chat-images/{attachment_id}/content")
def get_chat_image_content(document_id: int, attachment_id: str, token: str, db: Session = Depends(get_db)) -> Response:
    denied = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="聊天图片不存在或链接已过期")
    try:
        claims = decode_access_token(token)
        if (
            claims.get("scope") != CHAT_IMAGE_PREVIEW_SCOPE
            or int(claims.get("document_id")) != document_id
            or str(claims.get("attachment_id")) != attachment_id
        ):
            raise denied
        user = db.get(User, int(claims["sub"]))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise denied
    if user is None or not user.is_active:
        raise denied
    _get_accessible_document(db, document_id, user)
    attachment = db.get(ChatImageAttachment, attachment_id)
    if not attachment or attachment.document_id != document_id:
        raise denied
    try:
        data = read_attachment_bytes(db, attachment)
    except ChatImageError:
        raise denied
    return Response(data, media_type=attachment.content_type, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"})


def _restart_failure_events(
    error_message: str,
    html: str,
    partial_save_state: str = "none",
) -> list[dict[str, str]]:
    """Build terminal SSE payloads without retaining detached ORM instances."""
    return [
        {
            "event": "error",
            "data": json.dumps({"message": error_message}, ensure_ascii=False),
        },
        {
            "event": "final",
            "data": json.dumps(
                {
                    "content": error_message,
                    "html": html,
                    "html_changed": partial_save_state == "preserved",
                    "compliance": run_compliance_check(html).to_dict(),
                    "partial": True,
                    "partial_save_state": partial_save_state,
                    "run_status": AgentRunStatus.FAILED.value,
                    "error_message": error_message,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _agent_execution_error_message(message: str) -> str:
    """Return a safe, actionable browser message while retaining raw diagnostics."""
    if MODEL_CAPACITY_ERROR_PATTERN.search(message):
        return "当前模型服务繁忙或并发已满。请稍后重试，或更换其他可用模型后重新发送本轮请求。"
    prefix = "Agent 执行失败:"
    return message if message.startswith(prefix) else f"{prefix} {message}"


def _is_retryable_db_disconnect(exc: Exception) -> bool:
    """识别长模型调用期间被 MySQL 回收的连接。"""
    if not isinstance(exc, DBAPIError):
        return False
    if exc.connection_invalidated:
        return True
    detail = str(exc).lower()
    return any(
        marker in detail
        for marker in (
            "lost connection",
            "server has gone away",
            "connection reset",
            "connection aborted",
            "2006",
            "2013",
            "2055",
        )
    )


def _checkpoint_save_state(
    db: Session,
    run: AgentRun,
    document: Document,
    *,
    label: str,
) -> tuple[str, str, bool]:
    """Apply a durable write-tool candidate only when the base document is intact."""
    checkpoint = str(getattr(run, "checkpoint_html", "") or "")
    request_message = db.get(ChatMessage, run.user_message_id)
    source_html = request_message.html_before if request_message else None
    if not checkpoint or source_html is None:
        return "none", document.current_html, False
    if document.current_html != source_html:
        return "conflict", document.current_html, False
    if document.current_html == checkpoint:
        return "preserved", document.current_html, False
    document.current_html = checkpoint
    touch_document(document, run.user_id)
    if document.group:
        touch_group(document.group, run.user_id)
    create_document_version(db, document, run.user_id, DocumentVersionSource.AI, label)
    return "preserved", checkpoint, True


def _has_external_document_conflict(
    source_html: str,
    candidate_html: str,
    stored_html: str,
    agent_checkpoint_htmls: set[str],
) -> bool:
    """Keep own direct image writes distinct from an external document edit."""
    if stored_html == source_html or stored_html == candidate_html:
        return False
    return not (candidate_html != source_html and stored_html in agent_checkpoint_htmls)


def _persist_run_checkpoint(run_id: str, html: str) -> None:
    """Make completed edit-tool work recoverable before asking the model again."""
    if not html:
        return
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
        if (
            not run
            or run.status != AgentRunStatus.RUNNING
            or run.cancel_requested_at is not None
            or run.owner_id != agent_run_manager.worker_id
        ):
            return
        run.checkpoint_html = html
        db.commit()
        logger.warning("agent_trace run=%s checkpoint_persisted html_chars=%s", run_id, len(html))
    finally:
        db.close()


def _clear_run_checkpoint(run_id: str) -> None:
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
        if run and run.status == AgentRunStatus.RUNNING and run.cancel_requested_at is None and run.checkpoint_html:
            run.checkpoint_html = ""
            db.commit()
    finally:
        db.close()


async def _force_stuck_cancellation(run_id: str, document_id: int) -> None:
    """Terminate a run whose provider ignored task cancellation."""
    await asyncio.sleep(CANCEL_GRACE_SECONDS)
    live_run = agent_run_manager.get(run_id)
    if live_run and live_run.status in TERMINAL_STATUSES:
        return

    # Retry cancellation before force-finishing. Some provider clients only
    # observe cancellation after yielding control back to the event loop.
    agent_run_manager.request_cancel(run_id)
    db = SessionLocal()
    try:
        # Fence the executing worker before saving a forced terminal result.
        # This lock is acquired before the document lock, matching normal
        # terminal persistence and lease recovery.
        run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().first()
        document = (
            db.query(Document)
            .filter(Document.id == document_id)
            .with_for_update()
            .first()
        )
        if not run or not document or run.status != AgentRunStatus.CANCELLING:
            return

        save_state, report_html, html_changed = _checkpoint_save_state(
            db,
            run,
            document,
            label="AI 编辑（强制停止恢复）",
        )
        if save_state == "preserved":
            terminal_message = "已停止本轮操作；已保留已完成的排版修改。"
        elif save_state == "conflict":
            terminal_message = "已停止本轮操作；文档已被其他修改更新，候选排版未自动覆盖。"
        else:
            terminal_message = FORCED_CANCELLATION_MESSAGE

        run.status = AgentRunStatus.CANCELLED
        run.error_message = terminal_message
        run.finished_at = datetime.now(timezone.utc)
        run.owner_id = ""
        run.lease_expires_at = None
        run.last_phase = "forced_cancelled"
        run.last_progress_at = run.finished_at
        append_operation_log(
            db,
            actor=(
                db.get(User, user_id)
                if (user_id := getattr(run, "user_id", None)) is not None
                else None
            ),
            action="chat.run",
            resource_type="chat_run",
            resource_id=run.id,
            resource_name=str(getattr(document, "title", "")),
            document_id=document.id,
            session_id=run.session_id,
            status=OperationLogStatus.CANCELLED,
            summary="AI 对话已取消",
            details={"document_changed": html_changed, "forced_cancellation": True},
            client_ip=str(getattr(run, "origin_client_ip", "")),
            user_agent=str(getattr(run, "origin_user_agent", "")),
        )
        if not run.assistant_message_id:
            request_message = db.get(ChatMessage, run.user_message_id)
            assistant_message = ChatMessage(
                document_id=document.id,
                session_id=run.session_id,
                role=MessageRole.ASSISTANT,
                content=terminal_message,
                html_before=request_message.html_before if request_message else None,
                html_after=report_html if html_changed else None,
            )
            db.add(assistant_message)
            db.flush()
            run.assistant_message_id = assistant_message.id
        db.commit()

        terminal_data = {
            "content": terminal_message,
            "html": report_html,
            "html_changed": html_changed,
            "compliance": run_compliance_check(report_html).to_dict(),
            "cancelled": True,
            "partial": True,
            "partial_save_state": save_state,
            "run_status": AgentRunStatus.CANCELLED.value,
            "error_message": terminal_message,
        }
    finally:
        db.close()

    await agent_run_manager.publish(run_id, "final", terminal_data, force=True)
    await agent_run_manager.mark_terminal(run_id, AgentRunStatus.CANCELLED.value)


@router.get("/{document_id}/chat-sessions", response_model=list[ChatSessionRead])
def list_chat_sessions(
    document_id: int,
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    _get_accessible_document(db, document_id, current_user)
    ensure_default_chat_session(db, document_id)
    db.commit()
    query = db.query(ChatSession).filter(ChatSession.document_id == document_id)
    if not include_archived:
        query = query.filter(ChatSession.is_archived.is_(False))
    sessions = query.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()).all()
    return [_session_read(db, session) for session in sessions]


@router.post("/{document_id}/chat-sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    document_id: int,
    payload: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    title = payload.title.strip() or "新对话"
    if title == "新对话":
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.document_id == document_id,
                ChatSession.is_archived.is_(False),
                ChatSession.title == title,
                ~db.query(ChatMessage.id)
                .filter(ChatMessage.session_id == ChatSession.id)
                .exists(),
            )
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .first()
        )
        if session:
            return _session_read(db, session)

    session = ChatSession(document_id=document_id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.patch("/{document_id}/chat-sessions/{session_id}", response_model=ChatSessionRead)
def rename_chat_session(
    document_id: int,
    session_id: int,
    payload: ChatSessionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    session = _get_chat_session(db, document_id, session_id)
    session.title = payload.title.strip() or "新对话"
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.patch("/{document_id}/chat-sessions/{session_id}/image-settings", response_model=ChatSessionRead)
def update_chat_session_image_settings(
    document_id: int,
    session_id: int,
    payload: ChatSessionImageSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False)
    if payload.image_model_id is None:
        session.image_model_id = None
    else:
        model = db.get(AIImageModel, payload.image_model_id)
        if model is None or not can_access_image_model(current_user, model):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该图片模型的权限")
        if not model.provider.image_protocol or not model.provider.image_base_url:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该 Provider 尚未配置图片生成端点")
        session.image_model_id = model.id
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.post("/{document_id}/chat-sessions/{session_id}/archive", response_model=ChatSessionRead)
def archive_chat_session(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id)
    session.is_archived = True
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.delete("/{document_id}/chat-sessions/{session_id}/layout-reference", status_code=status.HTTP_204_NO_CONTENT)
def clear_chat_session_layout_reference(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False)
    clear_session_layout_reference(db, session.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{document_id}/chat-sessions/{session_id}/template-attachments", response_model=ChatSessionRead)
def replace_chat_session_template_attachments(
    document_id: int,
    session_id: int,
    payload: ChatSessionTemplateAttachmentsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False)
    try:
        replace_session_attached_templates(db, session.id, payload.template_ids)
        db.commit()
    except ChatSessionContextError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.refresh(session)
    return _session_read(db, session)


@router.delete("/{document_id}/chat-sessions/{session_id}/template-attachments/{template_id}", response_model=ChatSessionRead)
def remove_chat_session_template_attachment(
    document_id: int,
    session_id: int,
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False)
    current_ids = [item.id for item in session_attached_templates(db, session.id)]
    if template_id not in current_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该模板未附加到当前对话")
    replace_session_attached_templates(db, session.id, [item for item in current_ids if item != template_id])
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.delete("/{document_id}/chat-sessions/{session_id}/theme-context", response_model=ChatSessionRead)
def clear_chat_session_theme_context(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False)
    clear_session_theme_proposal(db, session.id)
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.post("/{document_id}/chat-sessions/{session_id}/restore", response_model=ChatSessionRead)
def restore_chat_session(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id)
    session.is_archived = False
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.post("/{document_id}/chat-sessions/{session_id}/truncate", response_model=ChatSessionRead)
def truncate_chat_session_context(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Hide all current conversation history from the model without deleting it."""
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False)
    latest_message_id = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.document_id == document_id,
            ChatMessage.session_id == session.id,
            ChatMessage.is_superseded.is_(False),
        )
        .order_by(ChatMessage.id.desc())
        .limit(1)
        .scalar()
    )
    if latest_message_id:
        session.context_start_message_id = int(latest_message_id)
    session.context_generation = int(session.context_generation or 0) + 1
    db.query(ChatSessionMemory).filter(ChatSessionMemory.session_id == session.id).delete(synchronize_session=False)
    db.query(ChatContextSnapshot).filter(ChatContextSnapshot.session_id == session.id, ChatContextSnapshot.is_active.is_(True)).update(
        {"is_active": False, "active_slot": None, "invalidation_reason": "context_truncated"}, synchronize_session=False
    )
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.post("/{document_id}/chat-sessions/{session_id}/restore-context", response_model=ChatSessionRead)
def restore_chat_session_context(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False)
    session.context_start_message_id = 0
    session.context_generation = int(session.context_generation or 0) + 1
    # Any summary created after truncation covers only the new segment and is
    # invalid once earlier turns become visible to the model again.
    db.query(ChatSessionMemory).filter(ChatSessionMemory.session_id == session.id).delete(synchronize_session=False)
    db.query(ChatContextSnapshot).filter(ChatContextSnapshot.session_id == session.id, ChatContextSnapshot.is_active.is_(True)).update(
        {"is_active": False, "active_slot": None, "invalidation_reason": "context_restored"}, synchronize_session=False
    )
    db.commit()
    db.refresh(session)
    return _session_read(db, session)


@router.get("/{document_id}/messages", response_model=list[ChatMessageRead])
def list_messages(
    document_id: int,
    session_id: int | None = None,
    include_hidden: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    document = _get_accessible_document(db, document_id, current_user)
    session = _get_chat_session(db, document_id, session_id) if session_id else _default_chat_session(db, document_id)
    orphaned_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.document_id == document.id,
            AgentRun.session_id == session.id,
            AgentRun.status == AgentRunStatus.FAILED,
            AgentRun.assistant_message_id.is_(None),
        )
        .all()
    )
    changed = False
    if orphaned_runs:
        for run in orphaned_runs:
            _persist_restart_failure(db, run, document)
        changed = True
    recovered_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.document_id == document.id,
            AgentRun.session_id == session.id,
            AgentRun.user_id == current_user.id,
            AgentRun.status == AgentRunStatus.FAILED,
            AgentRun.assistant_message_id.is_not(None),
            AgentRun.error_message.like("服务已重启，未完成的 Agent 已停止%"),
        )
        .all()
    )
    for run in recovered_runs:
        assistant_message = db.get(ChatMessage, run.assistant_message_id)
        if assistant_message is None or assistant_message.turn_blocks:
            continue
        events = (
            db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run.id)
            .order_by(AgentRunEvent.sequence)
            .all()
        )
        recovered_turn = recover_interrupted_turn(events, assistant_message.content)
        if not recovered_turn.has_recovered_context:
            continue
        assistant_message.content = recovered_turn.content
        assistant_message.tool_calls_json = json.dumps(recovered_turn.tool_calls, ensure_ascii=False)
        assistant_message.reasoning_trace_json = json.dumps(recovered_turn.reasoning_trace, ensure_ascii=False)
        assistant_message.turn_blocks_json = json.dumps(recovered_turn.turn_blocks, ensure_ascii=False)
        changed = True
    messages = _session_message_query(db, session, include_hidden=include_hidden).order_by(ChatMessage.id).all()
    for item in messages:
        if item.role == MessageRole.ASSISTANT:
            changed = _settle_persisted_assistant_message(item) or changed
    if changed:
        db.commit()
    usage_by_message = _assistant_message_model_usage(db, messages)
    return [_message_read(item, current_user, usage_by_message.get(item.id)) for item in messages]


@router.get("/{document_id}/chat-sessions/{session_id}/history-archives", response_model=list[ChatHistoryArchiveRead])
def list_history_archives(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ChatHistoryArchiveRead]:
    _get_accessible_document(db, document_id, current_user)
    session = _get_chat_session(db, document_id, session_id)
    archives = (
        db.query(ChatHistoryArchive)
        .filter(ChatHistoryArchive.session_id == session.id)
        .order_by(ChatHistoryArchive.created_at.desc(), ChatHistoryArchive.id.desc())
        .all()
    )
    return [
        ChatHistoryArchiveRead(
            id=archive.id,
            source_message_id=archive.source_message_id,
            reason=archive.reason,
            message_count=db.query(ChatMessage.id).filter(ChatMessage.history_archive_id == archive.id).count(),
            created_at=archive.created_at,
        )
        for archive in archives
    ]


@router.get("/{document_id}/chat-sessions/{session_id}/history-archives/{archive_id}/messages", response_model=list[ChatMessageRead])
def list_history_archive_messages(
    document_id: int,
    session_id: int,
    archive_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    _get_accessible_document(db, document_id, current_user)
    session = _get_chat_session(db, document_id, session_id)
    archive = (
        db.query(ChatHistoryArchive)
        .filter(ChatHistoryArchive.id == archive_id, ChatHistoryArchive.session_id == session.id)
        .first()
    )
    if archive is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="已放弃分支不存在")
    messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.document_id == document_id,
            ChatMessage.session_id == session.id,
            ChatMessage.history_archive_id == archive.id,
        )
        .order_by(ChatMessage.id)
        .all()
    )
    usage_by_message = _assistant_message_model_usage(db, messages)
    return [_message_read(item, current_user, usage_by_message.get(item.id)) for item in messages]


@router.get("/{document_id}/chat-context", response_model=ChatContextStatsRead)
def get_chat_context(
    document_id: int,
    model_id: int,
    session_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_accessible_document(db, document_id, current_user)
    session = _get_chat_session(db, document_id, session_id, allow_archived=False) if session_id else _default_chat_session(db, document_id)
    model = db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该模型的权限")
    attached_templates = _session_attached_template_payload(db, session.id)
    theme_reference = _theme_reference_payload(session_theme_proposal(db, session.id))
    history_rows = _session_message_query(db, session).order_by(ChatMessage.id).all()
    builder = AgentContextBuilder(
        db,
        document.id,
        session.id,
        model,
        HtmlEditSession(document.current_html, model.tool_result_max_tokens).workspace(),
        history_rows,
        context_budget_prompt()
        + "\n\n" + article_typography_prompt(typography_settings_payload(get_or_create_typography_settings(db)))
        + _layout_reference_context_prompt(
            session_layout_reference_agent_payload(get_session_layout_reference(db, session.id))
        )
        + _attached_template_prompt(attached_templates)
        + _theme_reference_prompt(theme_reference),
        model_call_tracker_factory=lambda: ModelCallTracker(
            model_id=model.id,
            user_id=current_user.id,
            source=ModelCallSource.AGENT_CONTEXT_COMPACTION,
            source_id=f"session:{session.id}",
        ),
    )
    return builder.snapshot()


@router.post("/{document_id}/chat-context/preview", response_model=ChatContextStatsRead)
def preview_chat_context(
    document_id: int,
    payload: ChatContextPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Estimate the prompt currently being composed without persisting it."""
    document = _get_accessible_document(db, document_id, current_user)
    session = _get_chat_session(db, document_id, payload.session_id, allow_archived=False)
    model = db.get(AIModel, payload.model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该模型的权限")
    preview_attachments = _pending_attachments(db, document.id, current_user.id, payload.image_attachment_ids)
    if preview_attachments and not model.is_multimodal:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前模型未启用图片交互，请切换多模态模型")
    attached_templates = (
        _attached_template_payload(db, payload.template_ids)
        if payload.template_ids is not None
        else _session_attached_template_payload(db, session.id)
    )
    theme_reference = _theme_reference_payload(session_theme_proposal(db, session.id))
    history_rows = _session_message_query(db, session).order_by(ChatMessage.id).all()
    selection_context = (
        json.dumps([item.model_dump() for item in payload.selected_elements], ensure_ascii=False)
        if payload.selected_elements
        else ""
    )
    builder = AgentContextBuilder(
        db,
        document.id,
        session.id,
        model,
        HtmlEditSession(document.current_html, model.tool_result_max_tokens).workspace(),
        history_rows,
        context_budget_prompt()
        + "\n\n" + article_typography_prompt(typography_settings_payload(get_or_create_typography_settings(db)))
        + _layout_reference_context_prompt(
            session_layout_reference_agent_payload(get_session_layout_reference(db, session.id))
        )
        + _attached_template_prompt(attached_templates)
        + _theme_reference_prompt(theme_reference),
        payload.message,
        selection_context,
        current_image_count=len(preview_attachments),
    )
    return builder.snapshot()


@router.post("/{document_id}/chat-context/compact", response_model=ChatContextStatsRead)
async def compact_chat_context(
    document_id: int,
    payload: ChatContextCompactRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create a durable snapshot without altering the immutable event ledger."""
    document = _get_accessible_document(db, document_id, current_user)
    _require_idle_document(db, document_id)
    session = _get_chat_session(db, document_id, payload.session_id, allow_archived=False)
    model = db.get(AIModel, payload.model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该模型的权限")
    attached_templates = _session_attached_template_payload(db, session.id)
    theme_reference = _theme_reference_payload(session_theme_proposal(db, session.id))
    history_rows = _session_message_query(db, session).order_by(ChatMessage.id).all()
    builder = AgentContextBuilder(
        db,
        document.id,
        session.id,
        model,
        HtmlEditSession(document.current_html, model.tool_result_max_tokens).workspace(),
        history_rows,
        context_budget_prompt()
        + "\n\n" + article_typography_prompt(typography_settings_payload(get_or_create_typography_settings(db)))
        + _layout_reference_context_prompt(
            session_layout_reference_agent_payload(get_session_layout_reference(db, session.id))
        )
        + _attached_template_prompt(attached_templates)
        + _theme_reference_prompt(theme_reference),
        model_call_tracker_factory=lambda: ModelCallTracker(
            model_id=model.id,
            user_id=current_user.id,
            source=ModelCallSource.AGENT_CONTEXT_COMPACTION,
            source_id=f"session:{session.id}",
        ),
    )
    compaction_model = build_compaction_model(model.provider, model)
    try:
        prepared = await builder.prepare(
            compaction_model,
            force_compaction=True,
            rebuild=payload.rebuild,
            trigger="manual_rebuild" if payload.rebuild else "manual",
        )
    except ContextBudgetError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # The compaction result is deliberately atomic.
        logger.exception("chat_context_compaction_failed document_id=%s session_id=%s", document_id, session.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"上下文压缩失败，可稍后重试：{exc}") from exc
    fallback_data = claim_thinking_capability_fallback_data(model.id, compaction_model)
    if fallback_data is not None:
        prepared.stats["thinking_capability_fallback"] = fallback_data
    return prepared.stats


@router.get("/{document_id}/chat-runs/active", response_model=AgentRunRead | None)
def get_active_run(
    document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AgentRunRead | None:
    _get_accessible_document(db, document_id, current_user)
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.document_id == document_id,
            AgentRun.user_id == current_user.id,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .order_by(AgentRun.created_at.desc())
        .first()
    )
    question = (
        db.query(ChatUserQuestion)
        .filter(ChatUserQuestion.run_id == run.id, ChatUserQuestion.status == ChatUserQuestionStatus.WAITING)
        .first()
        if run
        else None
    )
    return _run_read(run, user_question=question) if run else None


@router.get("/{document_id}/chat-runs/by-client-request/{client_request_id}", response_model=AgentRunRead | None)
def get_chat_run_by_client_request(
    document_id: int,
    client_request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunRead | None:
    """Reconcile an ambiguous POST without creating another editing run."""
    _get_accessible_document(db, document_id, current_user)
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.document_id == document_id,
            AgentRun.user_id == current_user.id,
            AgentRun.client_request_id == client_request_id,
        )
        .first()
    )
    return _run_read(run) if run else None


@router.get("/{document_id}/chat-runs/{run_id}", response_model=AgentRunRead)
def get_chat_run(
    document_id: int,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunRead:
    document = _get_accessible_document(db, document_id, current_user)
    run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
    if not run or run.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="执行记录不存在")
    if run.status == AgentRunStatus.FAILED and not run.assistant_message_id:
        _persist_restart_failure(db, run, document)
        db.commit()
    question = (
        db.query(ChatUserQuestion)
        .filter(ChatUserQuestion.run_id == run.id, ChatUserQuestion.status == ChatUserQuestionStatus.WAITING)
        .first()
    )
    return _run_read(run, user_question=question)


@router.post("/{document_id}/chat", response_model=AgentRunRead, status_code=status.HTTP_202_ACCEPTED)
async def start_chat_run(
    document_id: int,
    payload: ChatSendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunRead:
    # 同一文档的 Agent 会修改同一份 HTML；行锁覆盖“检查活动 run -> 创建 run”的窗口，
    # 避免两个并发 POST 同时通过检查而相互覆盖。
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    existing = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == current_user.id, AgentRun.client_request_id == payload.client_request_id)
        .first()
    )
    if existing:
        if existing.document_id != document.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请求标识已用于其他推文")
        if existing.session_id != payload.session_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请求标识已用于其他对话")
        return _run_read(existing)

    active_run = _active_run_for_document(db, document.id)
    if active_run:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前推文已有正在执行的 Agent，请等待完成或先停止")
    _require_agent_capacity(db, current_user.id)

    chat_session = _get_chat_session(db, document.id, payload.session_id, allow_archived=False)

    model = db.get(AIModel, payload.model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该模型的权限，请联系管理员")
    attachments = _pending_attachments(db, document.id, current_user.id, payload.image_attachment_ids)
    if attachments and not model.is_multimodal:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前模型未启用图片交互，请切换多模态模型")
    if not payload.message.strip() and not attachments:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息内容不能为空")
    effective_message = payload.message.strip() or "请分析所附图片，并继续处理当前推文。"
    try:
        attached_templates = (
            _template_payload_from_models(
                replace_session_attached_templates(db, chat_session.id, payload.template_ids)
            )
            if payload.template_ids is not None
            else _session_attached_template_payload(db, chat_session.id)
        )
    except ChatSessionContextError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    reask_activation: ReaskActivation | None = None
    inherited_theme_proposal_id: str | None = None
    if not payload.gzh_theme_proposal_id and payload.reask_from_message_id is not None:
        inherited_theme_proposal_id = reask_theme_proposal_id(
            db,
            source_message_id=payload.reask_from_message_id,
            document_id=document.id,
            session_id=chat_session.id,
            user_id=current_user.id,
        )
    if payload.reask_from_message_id is not None:
        try:
            reask_activation = activate_reask(
                db,
                document=document,
                session=chat_session,
                source_message_id=payload.reask_from_message_id,
                discard_document_changes=payload.reask_conflict_resolution == "discard_current_changes",
                expected_current_checksum=payload.reask_conflict_checksum,
            )
            touch_document(document, current_user.id)
            if payload.reask_conflict_resolution == "discard_current_changes":
                create_document_version(
                    db,
                    document,
                    current_user.id,
                    DocumentVersionSource.RESTORE,
                    "从历史对话重新提问，舍弃后续修改",
                )
        except ChatReaskConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "reask_document_conflict",
                    "message": str(exc),
                    "current_checksum": exc.current_checksum,
                },
            ) from exc
        except ChatReaskError as exc:
            # A stale client can retain a historical re-ask anchor after that
            # branch has already been archived. Give it a stable error code so
            # it can preserve the typed message while falling back to a normal
            # next turn instead of replaying this invalid anchor forever.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "reask_source_unavailable", "message": str(exc)},
            ) from exc
    theme_application: dict | None = None
    theme_proposal_id = payload.gzh_theme_proposal_id or inherited_theme_proposal_id
    if theme_proposal_id is None:
        # A failed or stopped initial application leaves the confirmed proposal
        # approved. Continue it in this session without making the user approve
        # the same unchanged proposal again.
        pending_proposal = session_approved_theme_proposal(db, chat_session.id)
        theme_proposal_id = pending_proposal.id if pending_proposal else None
    if theme_proposal_id:
        try:
            proposal = consume_approved_proposal(
                db,
                theme_proposal_id,
                document.id,
                current_user.id,
                document.current_html,
            )
        except GzhThemeError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if proposal.session_id is not None and proposal.session_id != chat_session.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="主题提案属于其他对话，请在原对话中使用")
        bind_session_theme_proposal(db, chat_session.id, proposal.id)
        theme_application = {
            "proposal_id": proposal.id,
            "theme_name": proposal.theme_name,
            "theme_markdown": proposal.theme_markdown,
            "apply_mode": proposal.apply_mode,
            "user_instructions": proposal.user_instructions,
            **proposal_theme_payload(proposal, include_html=True),
        }
    theme_reference: dict | None = None
    if not theme_application:
        theme_reference = _theme_reference_payload(session_theme_proposal(db, chat_session.id))
    layout_reference: dict | None = None
    if payload.layout_reference_id:
        try:
            cached_reference = get_layout_reference(db, payload.layout_reference_id, current_user.id)
            selected_asset_ids = list(dict.fromkeys(payload.layout_reference_selected_asset_ids))
            cached_reference.selected_assets(selected_asset_ids)
            if selected_asset_ids and not payload.layout_reference_assets_confirmed:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先确认已取得参考图片的复用授权")
            materialized = materialize_layout_reference(cached_reference, db, selected_asset_ids)
            binding = replace_session_layout_reference(
                db,
                chat_session.id,
                cached_reference,
                materialized,
                payload.layout_reference_imitation_strength,
            )
            layout_reference = session_layout_reference_agent_payload(binding)
        except LayoutReferenceError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    else:
        layout_reference = session_layout_reference_agent_payload(
            get_session_layout_reference(db, chat_session.id)
        )
    selected_elements = [element.model_dump() for element in payload.selected_elements]
    article_typography_settings = typography_settings_payload(get_or_create_typography_settings(db))
    reference_budget_prompt = context_budget_prompt() + _layout_reference_context_prompt(layout_reference)
    reference_budget_prompt += "\n\n" + article_typography_prompt(article_typography_settings)
    reference_budget_prompt += _attached_template_prompt(attached_templates)
    if theme_application:
        reference_budget_prompt += (
            f"\n\n已批准主题排版：{theme_application['theme_name']}（{theme_application['apply_mode']}）。"
            "主题组件将在 Agent 工具调用中按需读取。"
        )
    else:
        reference_budget_prompt += _theme_reference_prompt(theme_reference)
    selection_budget_context = json.dumps(selected_elements, ensure_ascii=False) if selected_elements else ""
    history_rows = _session_message_query(db, chat_session).order_by(ChatMessage.id).all()
    preflight = AgentContextBuilder(
        db,
        document.id,
        chat_session.id,
        model,
        HtmlEditSession(document.current_html, model.tool_result_max_tokens).workspace(),
        history_rows,
        reference_budget_prompt,
        payload.message,
        selection_budget_context,
        current_image_count=len(attachments),
    ).snapshot()
    if not preflight["can_fit_after_compaction"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "当前模型的压缩阈值无法容纳文档地图、最近对话和本轮请求；"
                "请在模型管理中提高压缩阈值或最大上下文窗口，或选择更大上下文模型"
            ),
        )

    chat_model, thinking_status = build_chat_model(
        model.provider,
        model,
        payload.thinking_mode,
        payload.thinking_effort,
        prompt_cache_key=build_agent_prompt_cache_key(model.provider, model, current_user.id),
    )
    compaction_model = build_compaction_model(model.provider, model)
    user_message = ChatMessage(
        document_id=document.id,
        session_id=chat_session.id,
        created_by_id=current_user.id,
        role=MessageRole.USER,
        content=payload.message,
        selected_elements_json=json.dumps(selected_elements, ensure_ascii=False) if selected_elements else "[]",
        template_refs_json=json.dumps([{"id": item["id"], "name": item["name"]} for item in attached_templates], ensure_ascii=False),
        gzh_theme_proposal_id=theme_application["proposal_id"] if theme_application else None,
        html_before=document.current_html,
    )
    db.add(user_message)
    db.flush()
    for attachment in attachments:
        attachment.message_id = user_message.id
    if chat_session.title == "新对话":
        generated_title = re.sub(r"\s+", " ", payload.message).strip()
        chat_session.title = generated_title[:48] or ("图片排版请求" if attachments else "新对话")

    origin_metadata = get_operation_request_metadata()
    run = AgentRun(
        id=str(uuid4()),
        document_id=document.id,
        session_id=chat_session.id,
        user_id=current_user.id,
        user_message_id=user_message.id,
        client_request_id=payload.client_request_id,
        origin_client_ip=origin_metadata.client_ip,
        origin_user_agent=origin_metadata.user_agent,
        status=AgentRunStatus.PENDING,
        owner_id=agent_run_manager.worker_id,
        heartbeat_at=datetime.now(timezone.utc),
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=agent_run_manager.lease_seconds),
    )
    db.add(run)
    db.flush()
    _persist_context_events(
        db,
        document_id=document.id,
        session_id=chat_session.id,
        message_id=user_message.id,
        run_id=run.id,
        events=[
            {
                "kind": ContextEventKind.USER.value,
                "payload": {"content": effective_message, "image_attachment_ids": [item.id for item in attachments], "template_ids": [item["id"] for item in attached_templates]},
            }
        ],
        fallback_content=effective_message,
    )
    db.commit()

    agent_run_manager.create(run.id)
    task = asyncio.create_task(
        _execute_agent_run(
            run_id=run.id,
            document_id=document.id,
            session_id=chat_session.id,
            user_id=current_user.id,
            chat_model=chat_model,
            thinking_status=thinking_status,
            thinking_effort=payload.thinking_effort,
            document_title=document.title,
            current_html=document.current_html,
            user_message=effective_message,
            user_message_id=user_message.id,
            model_id=model.id,
            compaction_model=compaction_model,
            image_attachment_ids=[item.id for item in attachments],
            selected_elements=selected_elements,
            layout_reference=layout_reference,
            theme_application=theme_application,
            theme_reference=theme_reference,
            attached_templates=attached_templates,
            reask_activated=reask_activation is not None,
            request_id=get_operation_request_id(),
            article_typography_settings=article_typography_settings,
        )
    )
    agent_run_manager.set_task(run.id, task)
    return _run_read(run, reask_activation)


def _utc_question_deadline(question: ChatUserQuestion) -> datetime:
    deadline = question.timeout_at
    if deadline is not None:
        return deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline.astimezone(timezone.utc)
    activity_at = question.last_activity_at or question.created_at or datetime.now(timezone.utc)
    activity_at = activity_at.replace(tzinfo=timezone.utc) if activity_at.tzinfo is None else activity_at.astimezone(timezone.utc)
    return activity_at + timedelta(seconds=max(1, int(settings.CHAT_USER_QUESTION_INACTIVITY_SECONDS)))


def _user_question_timeout_delay(question_id: str) -> float | None:
    """Return the remaining inactivity time, or None when the question ended."""
    db = SessionLocal()
    try:
        question = db.get(ChatUserQuestion, question_id)
        if question is None or question.status != ChatUserQuestionStatus.WAITING:
            return None
        run = db.get(AgentRun, question.run_id)
        if run is None or run.status != AgentRunStatus.WAITING_FOR_INPUT:
            _cancel_inconsistent_waiting_question(db, question, run)
            db.commit()
            return None
        return max(0.0, (_utc_question_deadline(question) - datetime.now(timezone.utc)).total_seconds())
    finally:
        db.close()


def _cancel_inconsistent_waiting_question(
    db: Session,
    question: ChatUserQuestion,
    run: AgentRun | None,
) -> None:
    """Close a question that cannot ever be resumed by the answer endpoint."""
    run_status = run.status.value if run is not None else "missing"
    question.status = ChatUserQuestionStatus.CANCELLED
    question.answer_json = json.dumps(
        {
            "action": "cancelled",
            "reason": "run_not_waiting_for_input",
            "run_status": run_status,
        },
        ensure_ascii=False,
    )
    question.answered_at = datetime.now(timezone.utc)
    logger.warning(
        "user_question_cancelled_inconsistent question=%s run=%s run_status=%s",
        question.id,
        question.run_id,
        run_status,
    )


def _cancel_waiting_questions_for_terminal_run(db: Session, run: AgentRun) -> None:
    """Keep terminal runs from leaving a resumable-looking question behind."""
    questions = (
        db.query(ChatUserQuestion)
        .filter(
            ChatUserQuestion.run_id == run.id,
            ChatUserQuestion.status == ChatUserQuestionStatus.WAITING,
        )
        .with_for_update()
        .all()
    )
    for question in questions:
        _cancel_inconsistent_waiting_question(db, question, run)


async def _auto_answer_timed_out_user_question(question_id: str) -> bool:
    """Resume a due question as its original user after an atomic deadline check."""
    db = SessionLocal()
    try:
        question = (
            db.query(ChatUserQuestion)
            .filter(ChatUserQuestion.id == question_id)
            .with_for_update()
            .one_or_none()
        )
        if question is None or question.status != ChatUserQuestionStatus.WAITING:
            return True
        if _utc_question_deadline(question) > datetime.now(timezone.utc):
            return False
        run = db.get(AgentRun, question.run_id)
        if run is None or run.status != AgentRunStatus.WAITING_FOR_INPUT:
            _cancel_inconsistent_waiting_question(db, question, run)
            db.commit()
            return True
        owner = db.get(User, question.user_id)
        if owner is None:
            logger.warning("user_question_timeout_owner_missing question=%s", question_id)
            _cancel_inconsistent_waiting_question(db, question, run)
            db.commit()
            return True
        try:
            await answer_chat_user_question(
                question.document_id,
                question.run_id,
                question.id,
                ChatUserQuestionAnswerRequest(
                    action="timeout",
                    client_request_id=f"{USER_QUESTION_TIMEOUT_CLIENT_REQUEST_PREFIX}{question.id}",
                ),
                owner,
                db,
            )
        except HTTPException as exc:
            # An interaction can extend the deadline between this read and
            # the row lock in the answer endpoint. Re-check rather than
            # turning an active user into a timeout answer.
            if exc.status_code == status.HTTP_409_CONFLICT:
                return False
            logger.warning("user_question_timeout_resume_rejected question=%s detail=%s", question_id, exc.detail)
            return True
        return True
    except Exception:  # noqa: BLE001 - a later restart can safely reschedule the durable question.
        logger.exception("user_question_timeout_resume_failed question=%s", question_id)
        return True
    finally:
        db.close()


async def _wait_for_user_question_timeout(question_id: str) -> None:
    try:
        while True:
            remaining = await asyncio.to_thread(_user_question_timeout_delay, question_id)
            if remaining is None:
                return
            if remaining > 0:
                await asyncio.sleep(remaining)
                continue
            if await _auto_answer_timed_out_user_question(question_id):
                return
            # The deadline was refreshed while this timer woke up. The next
            # iteration reads its durable value before scheduling another wait.
            # Never spin the event loop if an inconsistent external caller
            # keeps returning a conflict.
            await asyncio.sleep(USER_QUESTION_TIMEOUT_RETRY_DELAY_SECONDS)
    except asyncio.CancelledError:
        raise
    finally:
        _user_question_timeout_tasks.pop(question_id, None)


def schedule_user_question_timeout(question_id: str) -> None:
    existing = _user_question_timeout_tasks.get(question_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_wait_for_user_question_timeout(question_id))
    _user_question_timeout_tasks[question_id] = task


def cancel_user_question_timeout(question_id: str) -> None:
    """Cancel a local timer once its durable question is no longer waiting."""
    task = _user_question_timeout_tasks.pop(question_id, None)
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()


async def restore_waiting_user_question_timeouts() -> None:
    """Reinstall timers only for pauses that still have a waiting Agent run."""
    def waiting_ids() -> list[str]:
        db = SessionLocal()
        try:
            questions = (
                db.query(ChatUserQuestion)
                .filter(ChatUserQuestion.status == ChatUserQuestionStatus.WAITING)
                .all()
            )
            runnable_question_ids: list[str] = []
            for question in questions:
                run = db.get(AgentRun, question.run_id)
                if run is not None and run.status == AgentRunStatus.WAITING_FOR_INPUT:
                    runnable_question_ids.append(question.id)
                else:
                    _cancel_inconsistent_waiting_question(db, question, run)
            if len(runnable_question_ids) != len(questions):
                db.commit()
            return runnable_question_ids
        finally:
            db.close()

    for question_id in await asyncio.to_thread(waiting_ids):
        schedule_user_question_timeout(question_id)


@router.post(
    "/{document_id}/chat-runs/{run_id}/questions/{question_id}/answer",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def answer_chat_user_question(
    document_id: int,
    run_id: str,
    question_id: str,
    payload: ChatUserQuestionAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunRead:
    """Resume the exact pending tool call; this never creates a user message."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if not document or not can_access_document(current_user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
    question = db.query(ChatUserQuestion).filter(ChatUserQuestion.id == question_id).with_for_update().one_or_none()
    if not run or not question or run.document_id != document_id or question.run_id != run.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待答问题不存在")
    if run.user_id != current_user.id or question.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有发起本轮排版的用户可以回答该问题")
    if question.status != ChatUserQuestionStatus.WAITING:
        if question.answer_client_request_id == payload.client_request_id:
            return _run_read(run)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该问题已被回答或取消")
    duplicate_request = (
        db.query(ChatUserQuestion)
        .filter(
            ChatUserQuestion.answer_client_request_id == payload.client_request_id,
            ChatUserQuestion.id != question.id,
        )
        .first()
    )
    if duplicate_request is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该回答请求标识已用于其他问题")
    if run.status != AgentRunStatus.WAITING_FOR_INPUT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前 Agent 未处于等待回答状态")
    if payload.action == "timeout":
        if not payload.client_request_id.startswith(USER_QUESTION_TIMEOUT_CLIENT_REQUEST_PREFIX):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该回答类型仅供系统超时处理使用")
        if _utc_question_deadline(question) > datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户仍在操作提问面板")

    question_payload = question.question
    options = question_payload.get("options") if isinstance(question_payload.get("options"), list) else []
    option_by_id = {str(item.get("id")): item for item in options if isinstance(item, dict) and item.get("id")}
    canonical_answer: dict[str, object]
    if payload.action == "select":
        if any(option_id not in option_by_id for option_id in payload.option_ids):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="提交了不存在的选项")
        if not bool(question_payload.get("allow_multiple")) and len(payload.option_ids) != 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="该问题只能选择一个选项")
        canonical_answer = {
            "action": "selected",
            "selected_options": [
                {
                    "id": option_id,
                    "label": str(option_by_id[option_id].get("label") or ""),
                    "description": str(option_by_id[option_id].get("description") or ""),
                }
                for option_id in payload.option_ids
            ],
        }
    elif payload.action == "custom":
        canonical_answer = {"action": "custom_requirement", "requirement": payload.custom_requirement}
    elif payload.action == "skip":
        canonical_answer = {"action": "skipped"}
    else:
        canonical_answer = {
            "action": "no_response",
            "message": (
                f"用户在 {max(1, int(settings.CHAT_USER_QUESTION_INACTIVITY_SECONDS))} 秒内未回复。"
                "请基于现有文档和请求继续完成排版，不要再次提出相同问题。"
            ),
        }

    execution_context = _json_dict(question.execution_context_json)
    source_html = str(execution_context.get("current_html") or "")
    if document.current_html != source_html:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="等待回答期间文档已变化，不能安全恢复本轮排版")
    model = db.get(AIModel, question.model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="本轮使用的模型已被删除，无法继续")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你已无权继续使用本轮模型")
    try:
        resume_messages = restore_resume_messages(json.loads(question.resume_messages_json or "[]"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"待答问题的恢复上下文已损坏：{exc}") from exc
    completed_context_events = json.loads(question.completed_context_events_json or "[]")
    if not isinstance(completed_context_events, list):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="待答问题的历史上下文已损坏")
    timeline = _json_dict(question.timeline_json)
    timeline_tools = timeline.get("tool_calls") if isinstance(timeline.get("tool_calls"), list) else []
    timeline_blocks = timeline.get("turn_blocks") if isinstance(timeline.get("turn_blocks"), list) else []
    if _settle_user_question_timeline(
        timeline_tools,
        timeline_blocks,
        question.tool_call_id,
        canonical_answer,
    ):
        timeline["tool_calls"] = timeline_tools
        timeline["turn_blocks"] = timeline_blocks
        question.timeline_json = json.dumps(timeline, ensure_ascii=False)
    user_message = db.get(ChatMessage, run.user_message_id)
    if user_message is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="本轮原始请求不存在，无法继续")

    thinking_mode = str(execution_context.get("thinking_mode") or "auto")
    if thinking_mode not in {"auto", "enabled", "disabled"}:
        thinking_mode = "auto"
    thinking_effort = str(execution_context.get("thinking_effort") or "auto")
    if thinking_effort not in {"auto", "minimal", "low", "medium", "high", "xhigh", "max"}:
        thinking_effort = "auto"
    chat_model, thinking_status = build_chat_model(
        model.provider,
        model,
        thinking_mode,
        thinking_effort,
        prompt_cache_key=build_agent_prompt_cache_key(model.provider, model, current_user.id),
    )
    compaction_model = build_compaction_model(model.provider, model)
    question.status = ChatUserQuestionStatus.ANSWERED
    question.answer_json = json.dumps(canonical_answer, ensure_ascii=False)
    question.answer_client_request_id = payload.client_request_id
    question.answered_at = datetime.now(timezone.utc)
    run.status = AgentRunStatus.PENDING
    run.owner_id = ""
    run.lease_expires_at = None
    run.heartbeat_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError as exc:
        # The browser retries with the same idempotency key when an accepted
        # response is lost. A concurrent retry must resolve to the existing
        # resume instead of surfacing a database uniqueness error.
        db.rollback()
        existing_answer = (
            db.query(ChatUserQuestion)
            .filter(ChatUserQuestion.answer_client_request_id == payload.client_request_id)
            .one_or_none()
        )
        if existing_answer is not None and existing_answer.id == question_id:
            existing_run = db.get(AgentRun, run_id)
            if existing_run is not None:
                return _run_read(existing_run)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该回答已被并发处理，请刷新后继续") from exc

    cancel_user_question_timeout(question.id)

    resume_state = {
        "messages": resume_messages,
        "tool_result": {
            "tool_call_id": question.tool_call_id,
            "content": json.dumps(canonical_answer, ensure_ascii=False),
        },
        "completed_context_events": completed_context_events,
        "timeline": timeline,
    }
    agent_run_manager.create(run.id)
    task = asyncio.create_task(
        _execute_agent_run(
            run_id=run.id,
            document_id=document.id,
            session_id=run.session_id,
            user_id=current_user.id,
            chat_model=chat_model,
            thinking_status=thinking_status,
            thinking_effort=thinking_effort,
            document_title=str(execution_context.get("document_title") or document.title),
            current_html=source_html,
            user_message=user_message.content,
            user_message_id=user_message.id,
            model_id=model.id,
            compaction_model=compaction_model,
            image_attachment_ids=[item.id for item in user_message.image_attachments],
            selected_elements=execution_context.get("selected_elements") if isinstance(execution_context.get("selected_elements"), list) else [],
            layout_reference=execution_context.get("layout_reference") if isinstance(execution_context.get("layout_reference"), dict) else None,
            theme_application=execution_context.get("theme_application") if isinstance(execution_context.get("theme_application"), dict) else None,
            theme_reference=execution_context.get("theme_reference") if isinstance(execution_context.get("theme_reference"), dict) else None,
            attached_templates=execution_context.get("attached_templates") if isinstance(execution_context.get("attached_templates"), list) else [],
            request_id=get_operation_request_id(),
            resume_state=resume_state,
            article_typography_settings=execution_context.get("article_typography_settings") if isinstance(execution_context.get("article_typography_settings"), dict) else None,
        )
    )
    agent_run_manager.set_task(run.id, task)
    return _run_read(run)


@router.post(
    "/{document_id}/chat-runs/{run_id}/questions/{question_id}/activity",
    response_model=ChatUserQuestionActivityRead,
)
def record_chat_user_question_activity(
    document_id: int,
    run_id: str,
    question_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatUserQuestionActivityRead:
    """Extend a paused question only when its owner is actively using the panel."""
    _get_accessible_document(db, document_id, current_user)
    run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
    question = db.query(ChatUserQuestion).filter(ChatUserQuestion.id == question_id).with_for_update().one_or_none()
    if not run or not question or run.document_id != document_id or question.run_id != run.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待答问题不存在")
    if run.user_id != current_user.id or question.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有发起本轮排版的用户可以操作该问题")
    if run.status != AgentRunStatus.WAITING_FOR_INPUT or question.status != ChatUserQuestionStatus.WAITING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该问题已不再等待回答")
    now = datetime.now(timezone.utc)
    question.last_activity_at = now
    question.timeout_at = now + timedelta(seconds=max(1, int(settings.CHAT_USER_QUESTION_INACTIVITY_SECONDS)))
    db.commit()
    return ChatUserQuestionActivityRead(
        timeout_at=_utc_question_deadline(question),
        inactivity_seconds=max(1, int(settings.CHAT_USER_QUESTION_INACTIVITY_SECONDS)),
    )


@router.post("/{document_id}/chat-runs/{run_id}/cancel", response_model=AgentRunRead)
async def cancel_chat_run(
    document_id: int,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunRead:
    document = _get_accessible_document(db, document_id, current_user)
    run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
    if not run or run.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="执行记录不存在")
    if run.status in {AgentRunStatus.COMPLETED, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}:
        return _run_read(run)

    if run.status == AgentRunStatus.WAITING_FOR_INPUT:
        question = (
            db.query(ChatUserQuestion)
            .filter(ChatUserQuestion.run_id == run.id, ChatUserQuestion.status == ChatUserQuestionStatus.WAITING)
            .with_for_update()
            .one_or_none()
        )
        timeline = _json_dict(question.timeline_json) if question else {}
        tool_calls = timeline.get("tool_calls") if isinstance(timeline.get("tool_calls"), list) else []
        turn_blocks = timeline.get("turn_blocks") if isinstance(timeline.get("turn_blocks"), list) else []
        if question:
            _settle_user_question_timeline(
                tool_calls,
                turn_blocks,
                question.tool_call_id,
                {"action": "cancelled"},
            )
            question.status = ChatUserQuestionStatus.CANCELLED
        _settle_terminal_timeline(tool_calls, turn_blocks)
        terminal_message = "已停止本轮操作，未继续等待用户回答。"
        assistant_message = ChatMessage(
            document_id=document_id,
            session_id=run.session_id,
            role=MessageRole.ASSISTANT,
            content=terminal_message,
            tool_calls_json=json.dumps(tool_calls, ensure_ascii=False),
            turn_blocks_json=json.dumps(turn_blocks, ensure_ascii=False),
        )
        db.add(assistant_message)
        db.flush()
        run.assistant_message_id = assistant_message.id
        run.status = AgentRunStatus.CANCELLED
        run.error_message = terminal_message
        run.finished_at = datetime.now(timezone.utc)
        run.owner_id = ""
        run.lease_expires_at = None
        run.last_phase = "cancelled_waiting_for_input"
        run.last_progress_at = run.finished_at
        db.commit()
        if question:
            cancel_user_question_timeout(question.id)
        terminal_data = {
            "content": terminal_message,
            "html": document.current_html,
            "html_changed": False,
            "compliance": run_compliance_check(document.current_html).to_dict(),
            "cancelled": True,
            "partial": True,
            "partial_save_state": "none",
            "run_status": AgentRunStatus.CANCELLED.value,
            "error_message": terminal_message,
        }
        await agent_run_manager.publish(run_id, "final", terminal_data, force=True)
        await agent_run_manager.mark_terminal(run_id, AgentRunStatus.CANCELLED.value)
        return _run_read(run)

    run.status = AgentRunStatus.CANCELLING
    run.cancel_requested_at = datetime.now(timezone.utc)
    db.commit()
    agent_run_manager.request_cancel(run_id)
    asyncio.create_task(_force_stuck_cancellation(run_id, document_id))
    return _run_read(run)


@router.get("/{document_id}/chat-runs/{run_id}/events")
async def stream_chat_run_events(
    document_id: int,
    run_id: str,
    after: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    document = _get_accessible_document(db, document_id, current_user)
    run = db.get(AgentRun, run_id)
    if not run or run.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="执行记录不存在")

    if run.status in EXECUTING_RUN_STATUSES and _run_lease_expired(run):
        # The periodic recovery loop is the normal path. Keep this as a
        # synchronous safety net for a request that arrives exactly at lease
        # expiry, but use the same transactional recovery path so model calls,
        # checkpoints and the final replay event stay consistent.
        recover_expired_agent_runs(db)
        db.expire_all()
        run = db.get(AgentRun, run_id)
        document = db.get(Document, document_id)

    async def event_generator():
        async for item in agent_run_manager.events_after(run_id, after):
            if item.event == "user_question" and not await asyncio.to_thread(
                _is_current_waiting_question_event,
                run_id,
                item.data,
            ):
                continue
            event_age_ms = max(0, round((datetime.now(timezone.utc) - item.occurred_at).total_seconds() * 1000))
            event = {
                "event": item.event,
                "data": json.dumps({**item.data, "_event_age_ms": event_age_ms}, ensure_ascii=False),
            }
            if item.sequence > 0:
                event["id"] = str(item.sequence)
            yield event

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers=SSE_RESPONSE_HEADERS,
    )


async def _iterate_agent_events_with_timeout(events: AsyncIterator[dict]) -> AsyncIterator[dict]:
    """Guard silent provider stalls without treating streamed tool arguments as idle."""
    iterator = events.__aiter__()
    started_at = perf_counter()
    finalizing_turn = False
    awaiting_tool_arguments = False
    try:
        while True:
            elapsed = perf_counter() - started_at
            remaining = AGENT_MAX_RUNTIME_SECONDS - elapsed
            if remaining <= 0:
                raise RuntimeError(
                    f"Agent 运行超过 {AGENT_MAX_RUNTIME_SECONDS} 秒总时限，已停止本轮执行"
                )
            if finalizing_turn:
                idle_timeout = AGENT_TURN_FINALIZATION_TIMEOUT_SECONDS
            elif awaiting_tool_arguments:
                idle_timeout = AGENT_TOOL_ARGUMENT_IDLE_TIMEOUT_SECONDS
            else:
                idle_timeout = AGENT_EVENT_IDLE_TIMEOUT_SECONDS
            try:
                event = await asyncio.wait_for(iterator.__anext__(), timeout=min(idle_timeout, remaining))
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                if perf_counter() - started_at >= AGENT_MAX_RUNTIME_SECONDS:
                    raise RuntimeError(
                        f"Agent 运行超过 {AGENT_MAX_RUNTIME_SECONDS} 秒总时限，已停止本轮执行"
                    ) from exc
                if finalizing_turn:
                    raise RuntimeError(
                        f"Agent 在 {idle_timeout:g} 秒内未完成本轮响应整理，已停止本轮执行"
                    ) from exc
                if awaiting_tool_arguments:
                    raise RuntimeError(
                        f"Agent 在 {idle_timeout:g} 秒内未收到新的工具参数片段，已停止本轮执行"
                    ) from exc
                raise RuntimeError(
                    f"Agent 连续 {idle_timeout:g} 秒没有产生任何输出或工具事件，已停止本轮执行"
                ) from exc
            data = event.get("data") if isinstance(event, dict) else None
            event_name = event.get("event")
            if (
                event_name == "heartbeat"
                and isinstance(data, dict)
                and data.get("phase") == "model_turn_finalizing"
            ):
                finalizing_turn = True
            elif (
                event_name == "tool_call"
                and isinstance(data, dict)
                and data.get("preparing") is True
            ):
                finalizing_turn = False
                awaiting_tool_arguments = True
            elif (
                event_name == "heartbeat"
                and isinstance(data, dict)
                and data.get("phase") == "model_turn_started"
            ):
                finalizing_turn = False
                awaiting_tool_arguments = False
            elif event_name == "model_turn_retry":
                finalizing_turn = False
                awaiting_tool_arguments = False
            elif event_name in {"reasoning_delta", "text_delta", "tool_call", "tool_result", "final", "error"}:
                # Stats and transport heartbeats can be flushed after the
                # finalizing marker. They do not resume model work, so they
                # must not silently relax the short finalization timeout.
                finalizing_turn = False
                awaiting_tool_arguments = False
            yield event
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose:
            await aclose()


async def _execute_agent_run(
    *,
    run_id: str,
    document_id: int,
    session_id: int,
    user_id: int,
    chat_model,
    thinking_status,
    thinking_effort: str = "auto",
    document_title: str,
    current_html: str,
    user_message: str,
    user_message_id: int,
    model_id: int,
    compaction_model,
    image_attachment_ids: list[str],
    selected_elements: list[dict],
    layout_reference: dict | None = None,
    theme_application: dict | None = None,
    theme_reference: dict | None = None,
    attached_templates: list[dict] | None = None,
    reask_activated: bool = False,
    request_id: str = "",
    resume_state: dict | None = None,
    article_typography_settings: dict | None = None,
) -> None:
    """独立于浏览器 SSE 的执行任务；任何终态均保存已完成过程。"""
    log_process_memory(
        logger,
        stage="agent_start",
        worker_id=agent_run_manager.worker_id,
        run_id=run_id,
        document_id=document_id,
    )
    stream_db = SessionLocal()
    resume_timeline = resume_state.get("timeline", {}) if isinstance(resume_state, dict) else {}
    tool_trace: list[dict] = list(resume_timeline.get("tool_calls", [])) if isinstance(resume_timeline, dict) else []
    turn_blocks: list[dict] = list(resume_timeline.get("turn_blocks", [])) if isinstance(resume_timeline, dict) else []
    persisted_reasoning = resume_timeline.get("reasoning", {}) if isinstance(resume_timeline, dict) else {}
    persisted_reasoning = persisted_reasoning if isinstance(persisted_reasoning, dict) else {}
    reasoning_parts: list[str] = [str(persisted_reasoning.get("content", ""))] if persisted_reasoning.get("content") else []
    reasoning_status = str(persisted_reasoning.get("status", "idle"))
    reasoning_detail = str(persisted_reasoning.get("detail", ""))
    latest_html = current_html
    # Some image application tools commit their replacement immediately so
    # the stored object and document stay in sync while the Agent continues.
    # Keep the checkpoint snapshots produced by this run so terminal save does
    # not mistake that own write for an external document edit.
    agent_checkpoint_htmls: set[str] = set()
    terminal_context_events: list[dict] | None = None
    terminal_compliance: dict | None = None
    model_turn_checkpoint: dict[str, object] | None = None

    def finish_active_text_block() -> None:
        if turn_blocks and turn_blocks[-1].get("type") in {"thought", "content"}:
            block = turn_blocks[-1]
            block["state"] = "done"
            if block.get("type") == "thought":
                started_at = block.pop("_started_at", None)
                if started_at is not None:
                    block["duration_ms"] = max(0, round((perf_counter() - started_at) * 1000))

    def append_text_block(block_type: str, value: str) -> None:
        if not value:
            return
        if turn_blocks and turn_blocks[-1].get("type") == block_type and turn_blocks[-1].get("state") == "active":
            turn_blocks[-1]["content"] += value
            return
        finish_active_text_block()
        block = {
            "id": f"{block_type}-{len(turn_blocks) + 1}",
            "type": block_type,
            "state": "active",
            "content": value,
            "duration_ms": None,
        }
        if block_type == "thought":
            block["_started_at"] = perf_counter()
        turn_blocks.append(block)

    def partial_content(default: str) -> str:
        text = "".join(
            str(block.get("content", "")) for block in turn_blocks if block.get("type") == "content"
        ).strip()
        return text or default

    def fallback_terminal_data(
        terminal_status: AgentRunStatus,
        content: str,
        error_message: str = "",
    ) -> dict:
        """让 SSE 即使在数据库完全不可用时也能收到终态并停止。"""
        # Do not present an in-memory candidate as saved when terminal
        # persistence failed. Its durable checkpoint remains available for
        # audit/recovery, but the preview must reflect the stored document.
        html = current_html
        candidate_exists = latest_html != current_html
        return {
            "content": content,
            "html": html,
            "html_changed": False,
            "compliance": run_compliance_check(html).to_dict(),
            "cancelled": terminal_status == AgentRunStatus.CANCELLED,
            "partial": terminal_status != AgentRunStatus.COMPLETED,
            "partial_save_state": "unavailable" if candidate_exists else "none",
            "run_status": terminal_status.value,
            "error_message": error_message,
        }

    def persist_terminal(
        terminal_status: AgentRunStatus,
        content: str,
        *,
        error_message: str = "",
        compliance: dict | None = None,
        context_events: list[dict] | None = None,
        runtime_compaction: dict | None = None,
    ) -> dict:
        log_process_memory(
            logger,
            stage="agent_terminal_persist_start",
            worker_id=agent_run_manager.worker_id,
            run_id=run_id,
            status=terminal_status.value,
        )
        logger.warning(
            "agent_trace run=%s persist_start status=%s tools=%s blocks=%s html_changed=%s",
            run_id,
            terminal_status.value,
            len(tool_trace),
            len(turn_blocks),
            latest_html != current_html,
        )
        finish_active_text_block()
        _settle_terminal_timeline(tool_trace, turn_blocks)
        unresolved_edit_failure = _unresolved_edit_failure(tool_trace)
        if terminal_status == AgentRunStatus.COMPLETED and unresolved_edit_failure:
            content, error_message = unresolved_edit_failure
            terminal_status = AgentRunStatus.FAILED
        nonlocal reasoning_status, reasoning_detail
        if reasoning_parts:
            reasoning_status = "complete"
        elif thinking_status.requested == "enabled" and not thinking_status.applied:
            reasoning_status = "unavailable"
            reasoning_detail = thinking_status.detail
        elif thinking_status.requested == "enabled":
            reasoning_status = "unavailable"
            reasoning_detail = "模型未返回可展示的思考内容"

        # The model can hold this task for many minutes. A Session used to
        # assemble context/tool history may therefore retain a MySQL socket
        # that the server has already closed. Persist the terminal result in a
        # fresh Session so pool_pre_ping can select a live connection, and
        # retry one time if the connection dies between checkout and commit.
        for attempt in range(2):
            terminal_db = SessionLocal()
            try:
                # A cancellation watchdog may have already written the terminal
                # message while a provider call was unwinding. Never overwrite
                # that forced terminal result with late model output.
                terminal_db.expire_all()
                previous_run = (
                    terminal_db.query(AgentRun)
                    .filter(AgentRun.id == run_id)
                    .with_for_update()
                    .first()
                )
                if (
                    previous_run
                    and previous_run.status
                    in {AgentRunStatus.COMPLETED, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}
                    and previous_run.assistant_message_id
                ):
                    previous_message = terminal_db.get(ChatMessage, previous_run.assistant_message_id)
                    document = terminal_db.get(Document, document_id)
                    content = previous_message.content if previous_message else content
                    html = document.current_html if document else latest_html
                    if previous_message and previous_message.html_after:
                        previous_save_state = "preserved"
                    elif previous_run.checkpoint_html:
                        request_message = terminal_db.get(ChatMessage, previous_run.user_message_id)
                        previous_save_state = (
                            "conflict"
                            if request_message and document and document.current_html != request_message.html_before
                            else "unavailable"
                        )
                    else:
                        previous_save_state = "none"
                    return {
                        "content": content,
                        "html": html,
                        "html_changed": bool(previous_message and previous_message.html_after),
                        "compliance": run_compliance_check(html).to_dict(),
                        "cancelled": previous_run.status == AgentRunStatus.CANCELLED,
                        "partial": previous_run.status != AgentRunStatus.COMPLETED,
                        "partial_save_state": previous_save_state,
                        "run_status": previous_run.status.value,
                        "error_message": previous_run.error_message,
                    }

                # A remote cancellation or lease recovery clears ownership in
                # the same transaction that writes its terminal result. A late
                # provider response from this worker must not create a message,
                # alter the document or overwrite that terminal state.
                if not previous_run or previous_run.owner_id != agent_run_manager.worker_id:
                    document = terminal_db.get(Document, document_id)
                    html = document.current_html if document else current_html
                    return {
                        "content": previous_run.error_message if previous_run else content,
                        "html": html,
                        "html_changed": False,
                        "compliance": run_compliance_check(html).to_dict(),
                        "cancelled": bool(previous_run and previous_run.status == AgentRunStatus.CANCELLED),
                        "partial": True,
                        "partial_save_state": "none",
                        "run_status": previous_run.status.value if previous_run else AgentRunStatus.FAILED.value,
                        "error_message": previous_run.error_message if previous_run else "Agent 运行所有权已失效",
                    }

                # Once cancellation is durable, a response that arrives while
                # its task is winding down is a cancellation result, never a
                # successful completion.
                if (
                    terminal_status == AgentRunStatus.COMPLETED
                    and (
                        previous_run.status == AgentRunStatus.CANCELLING
                        or previous_run.cancel_requested_at is not None
                    )
                ):
                    terminal_status = AgentRunStatus.CANCELLED
                    error_message = previous_run.error_message or "已停止本轮操作。"
                    content = partial_content("已停止本轮操作。")

                document = (
                    terminal_db.query(Document)
                    .filter(Document.id == document_id)
                    .with_for_update()
                    .first()
                )
                document_conflict = bool(document) and _has_external_document_conflict(
                    current_html,
                    latest_html,
                    document.current_html,
                    agent_checkpoint_htmls,
                )
                candidate_exists = latest_html != current_html
                document_already_at_candidate = bool(document and document.current_html == latest_html)
                if document_conflict:
                    terminal_status = AgentRunStatus.FAILED
                    error_message = error_message or "运行期间文档已被手动或外部修改，Agent 结果未覆盖该修改"
                    if candidate_exists and "部分修改未自动保存，原因是文档冲突" not in content:
                        content = f"{content.rstrip()}\n\n部分修改未自动保存，原因是文档冲突。"
                elif terminal_status != AgentRunStatus.COMPLETED and candidate_exists:
                    if "本轮排版部分完成，已保留修改" not in content:
                        content = f"{content.rstrip()}\n\n本轮排版部分完成，已保留修改。"
                if terminal_status == AgentRunStatus.FAILED and error_message:
                    failure_summary = f"执行失败：{error_message}"
                    if failure_summary not in content:
                        content = f"{content.rstrip()}\n\n{failure_summary}"

                html_changed = latest_html != current_html and not document_conflict
                if document and html_changed and not document_already_at_candidate:
                    document.current_html = latest_html
                    touch_document(document, user_id)
                if document and html_changed:
                    if document.group and not document_already_at_candidate:
                        touch_group(document.group, user_id)
                    # Agent HTML patches can reference generated candidate
                    # URLs directly. Mark matching
                    # assets as applied so the seven-day candidate sweep does
                    # not remove an image that is now referenced by正文.
                    referenced_assets = terminal_db.query(GeneratedImageAsset).filter(
                        GeneratedImageAsset.is_applied.is_(False),
                        GeneratedImageAsset.url != "",
                        GeneratedImageAsset.generation.has(ImageGeneration.document_id == document_id),
                    ).all()
                    for asset in referenced_assets:
                        if asset.url in latest_html:
                            asset.is_applied = True
                            asset.applied_at = datetime.now(timezone.utc)

                assistant_message = ChatMessage(
                    document_id=document_id,
                    session_id=session_id,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    tool_calls_json=json.dumps(tool_trace, ensure_ascii=False),
                    reasoning_trace_json=json.dumps(
                        {"status": reasoning_status, "content": "".join(reasoning_parts), "detail": reasoning_detail},
                        ensure_ascii=False,
                    ),
                    turn_blocks_json=json.dumps(turn_blocks, ensure_ascii=False),
                    html_before=current_html if html_changed else None,
                    html_after=latest_html if html_changed else None,
                )
                terminal_db.add(assistant_message)
                terminal_db.flush()
                _persist_context_events(
                    terminal_db,
                    document_id=document_id,
                    session_id=session_id,
                    message_id=assistant_message.id,
                    run_id=run_id,
                    events=context_events,
                    fallback_content=content,
                )
                # The raw provider-visible events must be flushed first so a
                # runtime summary can point at a precise contiguous prefix.
                # Failed and cancelled runs never reach this promotion path.
                terminal_db.flush()
                if terminal_status == AgentRunStatus.COMPLETED:
                    _persist_runtime_compaction_snapshot(
                        terminal_db,
                        session_id=session_id,
                        assistant_message_id=assistant_message.id,
                        runtime_compaction=runtime_compaction,
                        model_id=model_id,
                        input_budget_tokens=max(0, int(stream_model.context_compaction_threshold_tokens) - AGENT_TOOL_SCHEMA_RESERVE_TOKENS),
                    )
                if document and html_changed and not document_already_at_candidate:
                    label = (
                        f"主题排版：{theme_application['theme_name']}"
                        if theme_application and terminal_status == AgentRunStatus.COMPLETED
                        else "AI 编辑" if terminal_status == AgentRunStatus.COMPLETED else "AI 编辑（未完成）"
                    )
                    create_document_version(terminal_db, document, user_id, DocumentVersionSource.AI, label)
                if theme_application and terminal_status == AgentRunStatus.COMPLETED and html_changed:
                    mark_proposal_applied(terminal_db, str(theme_application["proposal_id"]))

                run = terminal_db.get(AgentRun, run_id)
                if run:
                    run.status = terminal_status
                    run.error_message = error_message
                    run.assistant_message_id = assistant_message.id
                    run.finished_at = datetime.now(timezone.utc)
                    _cancel_waiting_questions_for_terminal_run(terminal_db, run)
                    started_at = run.created_at
                    duration_ms = 0
                    if started_at is not None:
                        try:
                            duration_ms = max(0, int((run.finished_at - started_at).total_seconds() * 1000))
                        except TypeError:
                            duration_ms = 0
                    actor = terminal_db.get(User, user_id)
                    append_operation_log(
                        terminal_db,
                        actor=actor,
                        action="chat.run",
                        resource_type="chat_run",
                        resource_id=run_id,
                        resource_name=document.title if document else document_title,
                        document_id=document_id,
                        session_id=session_id,
                        status=(
                            OperationLogStatus.SUCCEEDED
                            if terminal_status == AgentRunStatus.COMPLETED
                            else OperationLogStatus.CANCELLED
                            if terminal_status == AgentRunStatus.CANCELLED
                            else OperationLogStatus.FAILED
                        ),
                        summary=(
                            "AI 对话已完成"
                            if terminal_status == AgentRunStatus.COMPLETED
                            else "AI 对话已取消"
                            if terminal_status == AgentRunStatus.CANCELLED
                            else "AI 对话执行失败"
                        ),
                        error_summary="AI 对话执行失败" if terminal_status == AgentRunStatus.FAILED else "",
                        details={"model_id": model_id, "document_changed": html_changed, "duration_ms": duration_ms},
                        request_id=request_id,
                        client_ip=run.origin_client_ip,
                        user_agent=run.origin_user_agent,
                    )
                terminal_db.commit()
                logger.warning(
                    "agent_trace run=%s persist_committed status=%s assistant_message_id=%s attempt=%s",
                    run_id,
                    terminal_status.value,
                    assistant_message.id,
                    attempt + 1,
                )
                report_html = document.current_html if document_conflict and document else latest_html
                save_state = "conflict" if document_conflict and latest_html != current_html else (
                    "preserved" if html_changed else "none"
                )
                logger.warning(
                    "agent_trace run=%s terminal_save_result state=%s partial=%s html_changed=%s",
                    run_id,
                    save_state,
                    terminal_status != AgentRunStatus.COMPLETED,
                    html_changed,
                )
                log_process_memory(
                    logger,
                    stage="agent_terminal_persist_done",
                    worker_id=agent_run_manager.worker_id,
                    run_id=run_id,
                    status=terminal_status.value,
                )
                return {
                    "content": content,
                    "html": report_html,
                    "html_changed": html_changed,
                    "compliance": compliance if compliance and not document_conflict else run_compliance_check(report_html).to_dict(),
                    "cancelled": terminal_status == AgentRunStatus.CANCELLED,
                    "partial": terminal_status != AgentRunStatus.COMPLETED,
                    "partial_save_state": save_state,
                    "run_status": terminal_status.value,
                    "error_message": error_message,
                }
            except DBAPIError as exc:
                terminal_db.rollback()
                if attempt == 0 and _is_retryable_db_disconnect(exc):
                    logger.warning(
                        "agent_trace run=%s persist_db_disconnect retrying detail=%s",
                        run_id,
                        str(exc),
                    )
                    continue
                raise
            finally:
                terminal_db.close()

    def persist_waiting_question(data: dict) -> ChatUserQuestion:
        """Atomically publish a durable pause before ending the worker task."""
        finish_active_text_block()
        question_payload = data.get("question") if isinstance(data.get("question"), dict) else {}
        resume_messages = data.get("resume_messages") if isinstance(data.get("resume_messages"), list) else []
        completed_events = data.get("completed_context_events") if isinstance(data.get("completed_context_events"), list) else []
        tool_call_id = str(data.get("tool_call_id") or "")
        if not tool_call_id or not question_payload or not resume_messages:
            raise RuntimeError("模型提问缺少可恢复上下文")
        for item in reversed(tool_trace):
            if item.get("id") == tool_call_id and item.get("name") == "ask_user":
                item["status"] = "waiting"
                item["preparing"] = False
                item["result"] = "等待用户回答"
                item["activity"] = {"kind": "question", "summary": "等待用户回答"}
                break
        execution_context = {
            "document_title": document_title,
            "current_html": current_html,
            "selected_elements": selected_elements,
            "layout_reference": layout_reference,
            "theme_application": theme_application,
            "theme_reference": theme_reference,
            "attached_templates": attached_templates or [],
            "thinking_mode": thinking_status.requested,
            "thinking_effort": thinking_effort,
            "article_typography_settings": article_typography_settings,
        }
        now = datetime.now(timezone.utc)
        timeout_at = now + timedelta(
            seconds=max(1, int(settings.CHAT_USER_QUESTION_INACTIVITY_SECONDS))
        )
        question = ChatUserQuestion(
            id=str(uuid4()),
            run_id=run_id,
            document_id=document_id,
            session_id=session_id,
            user_id=user_id,
            model_id=model_id,
            tool_call_id=tool_call_id,
            status=ChatUserQuestionStatus.WAITING,
            question_json=json.dumps(question_payload, ensure_ascii=False),
            resume_messages_json=json.dumps(resume_messages, ensure_ascii=False),
            completed_context_events_json=json.dumps(completed_events, ensure_ascii=False),
            execution_context_json=json.dumps(execution_context, ensure_ascii=False),
            last_activity_at=now,
            timeout_at=timeout_at,
            timeline_json=json.dumps(
                {
                    "tool_calls": tool_trace,
                    "turn_blocks": turn_blocks,
                    "reasoning": {
                        "status": reasoning_status,
                        "content": "".join(reasoning_parts),
                        "detail": reasoning_detail,
                    },
                },
                ensure_ascii=False,
            ),
        )
        waiting_db = SessionLocal()
        try:
            run = waiting_db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
            if not run or run.status not in {AgentRunStatus.RUNNING, AgentRunStatus.PENDING}:
                raise RuntimeError("Agent 运行已不再可等待用户回答")
            waiting_db.add(question)
            run.status = AgentRunStatus.WAITING_FOR_INPUT
            run.owner_id = ""
            run.lease_expires_at = None
            run.heartbeat_at = datetime.now(timezone.utc)
            waiting_db.commit()
            # ``commit`` expires ORM attributes by default. The worker must
            # still publish this question after this short-lived session
            # closes, so load and detach the complete durable record first.
            waiting_db.refresh(question)
            waiting_db.expunge(question)
            return question
        except Exception:
            waiting_db.rollback()
            raise
        finally:
            waiting_db.close()

    try:
        logger.warning("agent_trace run=%s execution_started document_id=%s", run_id, document_id)
        cancelled_before_start = await agent_run_manager.mark_started(run_id)
        if cancelled_before_start is None:
            logger.warning("agent_trace run=%s execution_not_owner", run_id)
            return
        run = stream_db.get(AgentRun, run_id)
        if run:
            run.status = AgentRunStatus.CANCELLING if cancelled_before_start else AgentRunStatus.RUNNING
            stream_db.commit()
        if cancelled_before_start:
            terminal_data = persist_terminal(
                AgentRunStatus.CANCELLED, "已停止本轮操作，未执行任何修改。"
            )
            await agent_run_manager.publish(run_id, "final", terminal_data)
            await agent_run_manager.mark_terminal(run_id, "cancelled")
            return

        await agent_run_manager.publish(
            run_id,
            "agent_status",
            {"thinking": thinking_status.to_dict()},
        )
        stream_model = stream_db.get(AIModel, model_id)
        if not stream_model:
            raise RuntimeError("本轮使用的模型已被删除")
        history_rows = (
            stream_db.query(ChatMessage)
            .filter(
                ChatMessage.document_id == document_id,
                ChatMessage.session_id == session_id,
                ChatMessage.id != user_message_id,
                ChatMessage.is_superseded.is_(False),
            )
            .order_by(ChatMessage.id)
            .all()
        )
        stream_session = _get_chat_session(stream_db, document_id, session_id, allow_archived=False)
        if stream_session.context_start_message_id > 0:
            history_rows = [
                row for row in history_rows if row.id > stream_session.context_start_message_id
            ]
        def persist_agent_checkpoint(html: str) -> None:
            if html:
                agent_checkpoint_htmls.add(html)
            _persist_run_checkpoint(run_id, html)

        edit_session = HtmlEditSession(
            current_html,
            stream_model.tool_result_max_tokens,
            checkpoint_callback=persist_agent_checkpoint,
            cancel_requested=lambda: agent_run_manager.is_cancel_requested(run_id),
        )
        # History reads happen after potentially long model calls. Give them
        # isolated sessions so a stale stream connection cannot fail the run.
        history_workspace = DocumentHistoryWorkspace(
            stream_db,
            document_id,
            stream_model.tool_result_max_tokens,
            session_factory=SessionLocal,
        )
        if article_typography_settings is None:
            article_typography_settings = typography_settings_payload(get_or_create_typography_settings(stream_db))
        budget_prompt = (
            context_budget_prompt()
            + "\n\n"
            + article_typography_prompt(article_typography_settings)
            + _layout_reference_context_prompt(layout_reference)
        )
        selection_budget_context = json.dumps(selected_elements, ensure_ascii=False) if selected_elements else ""
        context_builder = AgentContextBuilder(
            stream_db,
            document_id,
            session_id,
            stream_model,
            edit_session.workspace(),
            history_rows,
            budget_prompt,
            user_message,
            selection_budget_context,
            current_image_count=len(image_attachment_ids),
            exclude_message_id=user_message_id,
            model_call_tracker_factory=lambda: ModelCallTracker(
                model_id=model_id,
                user_id=user_id,
                source=ModelCallSource.AGENT_CONTEXT_COMPACTION,
                source_id=run_id,
            ),
        )
        preflight_stats = context_builder.snapshot()
        await agent_run_manager.publish(run_id, "context_stats", {**preflight_stats, "state": "preparing"})
        if preflight_stats.get("requires_compaction"):
            await agent_run_manager.publish(
                run_id,
                "context_stats",
                {
                    **preflight_stats,
                    "state": "compacting",
                    "compaction_location": "新分支请求前" if reask_activated else "初始推理前",
                },
            )
        prepared_context = await context_builder.prepare(compaction_model)
        fallback_data = claim_thinking_capability_fallback_data(model_id, compaction_model)
        if fallback_data is not None:
            await agent_run_manager.publish(run_id, "thinking_capability_fallback", fallback_data)
        await agent_run_manager.publish(run_id, "context_stats", prepared_context.stats)
        # The model call can take minutes. End the read transaction before it
        # begins so the cancellation endpoint can update this run promptly.
        stream_db.commit()
        if layout_reference and not resume_state:
            reference_tool = {
                "id": "layout-reference",
                "name": "apply_layout_reference",
                "arguments": {
                    "title": layout_reference.get("title", ""),
                    "imitation_strength": layout_reference.get("imitation_strength", "structure"),
                },
                "status": "success",
                "result": (
                    f"已绑定参考排版模板（{layout_reference.get('imitation_strength', 'structure')}）与 "
                    f"{layout_reference.get('image_assets', 0)} 个已授权素材；"
                    "Agent 将按需读取模板源码，并保留当前文案和图片。"
                ),
                "html_changed": False,
                "activity": {
                    "kind": "reference",
                    "summary": (
                        f"已绑定{layout_reference.get('imitation_strength', 'structure')}参考模板与 "
                        f"{layout_reference.get('image_assets', 0)} 个素材"
                    ),
                },
            }
            tool_trace.append(reference_tool)
            turn_blocks.append(
                {"id": "block-layout-reference", "type": "tool", "state": "done", "content": "", "tool": reference_tool}
            )
            await agent_run_manager.publish(
                run_id,
                "tool_call",
                {"id": reference_tool["id"], "name": reference_tool["name"], "arguments": reference_tool["arguments"]},
            )
            await agent_run_manager.publish(
                run_id,
                "tool_result",
                {
                    "id": reference_tool["id"],
                    "name": reference_tool["name"],
                    "result": reference_tool["result"],
                    "activity": reference_tool["activity"],
                },
            )
        if theme_application and not resume_state:
            theme_tool = {
                "id": "gzh-theme-proposal",
                "name": "apply_gzh_theme_proposal",
                "arguments": {
                    "theme_name": theme_application["theme_name"],
                    "apply_mode": theme_application["apply_mode"],
                    "user_instructions": theme_application.get("user_instructions", ""),
                },
                "status": "success",
                "result": "已确认主题排版，将在保留正文、链接和图片语义的前提下执行全文替换。",
                "html_changed": False,
                "activity": {
                    "kind": "theme",
                    "summary": f"已确认主题「{theme_application['theme_name']}」",
                    "details": {
                        "apply_mode": theme_application["apply_mode"],
                        "user_instructions": theme_application.get("user_instructions", ""),
                        "article_type": theme_application.get("article_type", ""),
                        "recipe_id": theme_application.get("recipe_id", ""),
                        "selected_component_ids": theme_application.get("selected_component_ids", []),
                    },
                },
            }
            tool_trace.append(theme_tool)
            turn_blocks.append(
                {"id": "block-gzh-theme-proposal", "type": "tool", "state": "done", "content": "", "tool": theme_tool}
            )
            await agent_run_manager.publish(
                run_id,
                "tool_call",
                {"id": theme_tool["id"], "name": theme_tool["name"], "arguments": theme_tool["arguments"]},
            )
            await agent_run_manager.publish(
                run_id,
                "tool_result",
                {
                    "id": theme_tool["id"],
                    "name": theme_tool["name"],
                    "result": theme_tool["result"],
                    "activity": theme_tool["activity"],
                },
            )
        completed = False
        resume_messages = resume_state.get("messages") if isinstance(resume_state, dict) else None
        resume_tool_result = resume_state.get("tool_result") if isinstance(resume_state, dict) else None
        prior_context_events = resume_state.get("completed_context_events") if isinstance(resume_state, dict) else None
        if resume_state:
            resumed_question_call_id = str((resume_tool_result or {}).get("tool_call_id") or "")
            resumed_question_answer = _json_dict(str((resume_tool_result or {}).get("content") or "{}"))
            timeline_question_tool_id = _settle_user_question_timeline(
                tool_trace,
                turn_blocks,
                resumed_question_call_id,
                resumed_question_answer,
            )
            if timeline_question_tool_id:
                question_result, question_activity = _user_question_resolution_presentation(resumed_question_answer)
                await agent_run_manager.publish(
                    run_id,
                    "tool_result",
                    {
                        "id": timeline_question_tool_id,
                        "name": "ask_user",
                        "result": question_result,
                        "activity": question_activity,
                    },
                )
        current_image_attachments = (
            stream_db.query(ChatImageAttachment)
            .filter(
                ChatImageAttachment.id.in_(image_attachment_ids),
                ChatImageAttachment.message_id == user_message_id,
            )
            .order_by(ChatImageAttachment.created_at)
            .all()
            if image_attachment_ids
            else []
        )
        current_user_content = user_message_content(
            stream_db,
            user_message,
            current_image_attachments,
            provider_type=stream_model.provider.provider_type.value,
            include_images=stream_model.is_multimodal,
        )
        selected_image_model = _agent_image_model(
            stream_db,
            user_id,
            stream_session.image_model_id,
        )
        image_generation_context = {
            "image_model_id": selected_image_model.id if selected_image_model else None,
            "model_name": selected_image_model.display_name if selected_image_model else "管理员默认图片模型",
        }
        # Attachment hydration starts a new read transaction after the
        # preflight commit.  ``run_agent_loop`` can run for minutes, so end it
        # before entering the graph; every later persistence path owns a
        # short-lived, dedicated Session.
        stream_db.rollback()
        retried_for_context = False
        active_layout_reference = layout_reference
        while not completed:
            context_error = ""
            async for evt in _iterate_agent_events_with_timeout(
                run_agent_loop(
                    chat_model,
                    document_title,
                    current_html,
                    user_message,
                    prepared_context.workspace_map,
                    prepared_context.memory,
                    prepared_context.history,
                    selected_elements,
                    active_layout_reference,
                    edit_session,
                    history_workspace,
                    max(1, int(stream_model.context_compaction_threshold_tokens) - AGENT_TOOL_SCHEMA_RESERVE_TOKENS),
                    run_id,
                    ToolOutputStore(document_id=document_id, session_id=session_id, run_id=run_id),
                    theme_application,
                    user_id,
                    theme_reference,
                    attached_templates,
                    current_user_content,
                    compaction_model=compaction_model,
                    model_id=model_id,
                    resume_messages=resume_messages,
                    resume_tool_result=resume_tool_result,
                    prior_context_events=prior_context_events,
                    image_generation_context=image_generation_context,
                    model_is_multimodal=stream_model.is_multimodal,
                    provider_type=stream_model.provider.provider_type.value,
                    article_typography_settings=article_typography_settings,
                )
            ):
                event = evt["event"]
                data = evt["data"]
                if event in {"final", "error"} or (
                    event == "heartbeat" and data.get("phase") == "model_turn_finalizing"
                ):
                    logger.warning(
                        "agent_trace run=%s agent_event=%s phase=%s",
                        run_id,
                        event,
                        data.get("phase", "-"),
                    )
                if event == "heartbeat" and data.get("phase") == "model_turn_started":
                    log_process_memory(
                        logger,
                        stage="model_start",
                        worker_id=agent_run_manager.worker_id,
                        run_id=run_id,
                        turn=data.get("turn"),
                    )
                elif event == "heartbeat" and data.get("phase") == "model_turn_finalizing":
                    log_process_memory(
                        logger,
                        stage="model_finalize",
                        worker_id=agent_run_manager.worker_id,
                        run_id=run_id,
                        turn=data.get("turn"),
                    )
                if event == "reasoning_delta":
                    reasoning_text = data.get("text", "")
                    reasoning_parts.append(reasoning_text)
                    append_text_block("thought", reasoning_text)
                    reasoning_status = "thinking"
                elif event == "heartbeat" and data.get("phase") == "model_turn_started":
                    # A provider retry restarts this one model turn. Keep all
                    # completed earlier tools, but make the transient model
                    # output recoverable so the persisted terminal record
                    # cannot contain text or pending calls from both attempts.
                    model_turn_checkpoint = {
                        "turn": data.get("turn"),
                        "tool_trace": copy.deepcopy(tool_trace),
                        "turn_blocks": copy.deepcopy(turn_blocks),
                        "reasoning_parts": list(reasoning_parts),
                        "reasoning_status": reasoning_status,
                        "reasoning_detail": reasoning_detail,
                        "latest_html": latest_html,
                    }
                elif event == "model_turn_retry":
                    if model_turn_checkpoint and (
                        data.get("turn") is None or data.get("turn") == model_turn_checkpoint.get("turn")
                    ):
                        tool_trace, turn_blocks, interrupted_tool_ids = _preserve_retried_tool_previews(
                            model_turn_checkpoint["tool_trace"],
                            model_turn_checkpoint["turn_blocks"],
                            tool_trace,
                            turn_blocks,
                            data,
                        )
                        if interrupted_tool_ids:
                            data = {**data, "interrupted_tool_ids": interrupted_tool_ids}
                        reasoning_parts = list(model_turn_checkpoint["reasoning_parts"])
                        reasoning_status = str(model_turn_checkpoint["reasoning_status"])
                        reasoning_detail = str(model_turn_checkpoint["reasoning_detail"])
                        latest_html = str(model_turn_checkpoint["latest_html"])
                elif event == "text_delta":
                    append_text_block("content", data.get("text", ""))
                elif event == "tool_call":
                    finish_active_text_block()
                    tool_id = str(data.get("id") or f"tool-{len(tool_trace) + 1}")
                    existing_tool = next((item for item in tool_trace if item["id"] == tool_id), None)
                    if existing_tool:
                        existing_tool["name"] = data.get("name", existing_tool["name"])
                        existing_tool["arguments"] = data.get("arguments", existing_tool["arguments"])
                        if isinstance(data.get("argument_tokens"), int):
                            existing_tool["argument_tokens"] = max(
                                int(existing_tool.get("argument_tokens") or 0),
                                max(0, data["argument_tokens"]),
                            )
                        if not data.get("preparing"):
                            existing_tool["preparing"] = False
                    else:
                        tool_entry = {
                            "id": tool_id,
                            "name": data.get("name", "unknown"),
                            "arguments": data.get("arguments", {}),
                            "status": "running",
                            "preparing": bool(data.get("preparing")),
                            "argument_tokens": max(0, int(data.get("argument_tokens") or 0)),
                            "result": None,
                            "html_changed": False,
                            "activity": None,
                        }
                        tool_trace.append(tool_entry)
                        log_process_memory(
                            logger,
                            stage="tool_start",
                            worker_id=agent_run_manager.worker_id,
                            run_id=run_id,
                            tool_name=tool_entry["name"],
                        )
                        turn_blocks.append(
                            {
                                "id": f"block-{tool_entry['id']}",
                                "type": "tool",
                                "state": "done",
                                "content": "",
                                "tool": tool_entry,
                            }
                        )
                elif event == "tool_result":
                    result_tool_id = str(data.get("id") or "")
                    matched_tool = next(
                        (
                            item
                            for item in reversed(tool_trace)
                            if item.get("id") == result_tool_id
                        ),
                        None,
                    ) if result_tool_id else next(
                        (
                            item
                            for item in reversed(tool_trace)
                            if item.get("name") == data.get("name") and item.get("status") == "running"
                        ),
                        None,
                    )
                    if matched_tool:
                        matched_tool["result"] = data.get("result", "")
                        matched_tool["status"] = "error" if str(data.get("result", "")).startswith("错误") else "success"
                        matched_tool["preparing"] = False
                        matched_tool["html_changed"] = bool(data.get("html"))
                        matched_tool["activity"] = data.get("activity")
                    log_process_memory(
                        logger,
                        stage="tool_done",
                        worker_id=agent_run_manager.worker_id,
                        run_id=run_id,
                        tool_name=data.get("name"),
                    )
                    if data.get("html"):
                        latest_html = data["html"]
                    else:
                        # Tool activity is intentionally payload-safe; the
                        # mutable session remains the source for partial
                        # persistence if the run is cancelled after an edit.
                        latest_html = edit_session.html
                elif event == "user_question":
                    question = persist_waiting_question(data)
                    safe_question = _question_read(question)
                    if safe_question is None:
                        raise RuntimeError("待答问题保存失败")
                    await agent_run_manager.publish(
                        run_id,
                        "user_question",
                        safe_question.model_dump(),
                        force=True,
                    )
                    await agent_run_manager.mark_waiting(run_id)
                    schedule_user_question_timeout(question.id)
                    completed = True
                    break
                elif event == "context_stats":
                    # 运行时的 provider 用量和工具循环压缩是诊断信息；主仪表盘
                    # 仍表示本轮构建完成后的下次输入预算，不能被单次调用覆盖。
                    await agent_run_manager.publish(
                        run_id,
                        "context_stats",
                        _merge_runtime_context_stats(prepared_context.stats, data),
                    )
                    continue
                elif event == "error":
                    detail = str(data.get("message", "Agent 执行失败"))
                    if isinstance(data.get("context_events"), list):
                        terminal_context_events = data["context_events"]
                    if data.get("rollback_html"):
                        # A theme candidate may already have emitted edit
                        # events. Strict validation is a terminal gate, so
                        # discard that transient candidate before failure
                        # persistence has a chance to create a version.
                        latest_html = str(data.get("html", current_html))
                        edit_session.html = latest_html
                        edit_session.edited = False
                        await asyncio.to_thread(_clear_run_checkpoint, run_id)
                        if isinstance(data.get("compliance"), dict):
                            terminal_compliance = data["compliance"]
                    # Retry only before a model response or tool mutation is
                    # visible. Replaying after an edit would risk duplicate
                    # writes and must remain a terminal failure.
                    if (
                        not retried_for_context
                        and not edit_session.edited
                        and not reasoning_parts
                        and not any(block.get("type") == "content" and block.get("content") for block in turn_blocks)
                        and _is_context_limit_error(detail)
                    ):
                        context_error = detail
                        break
                    raise RuntimeError(detail)
                elif event == "final":
                    latest_html = data.get("html") or latest_html
                    logger.warning("agent_trace run=%s final_received_from_graph", run_id)
                    terminal_data = persist_terminal(
                        AgentRunStatus.COMPLETED,
                        data.get("content") or "已完成本轮编辑。",
                        compliance=data.get("compliance"),
                        context_events=data.get("context_events") if isinstance(data.get("context_events"), list) else None,
                        runtime_compaction=data.get("runtime_compaction") if isinstance(data.get("runtime_compaction"), dict) else None,
                    )
                    logger.warning("agent_trace run=%s final_publish_start", run_id)
                    await agent_run_manager.publish(run_id, "final", terminal_data)
                    await agent_run_manager.mark_terminal(run_id, terminal_data["run_status"])
                    logger.warning("agent_trace run=%s terminal_marked status=%s", run_id, terminal_data["run_status"])
                    completed = True
                    break

                await agent_run_manager.publish(run_id, event, data)

            if context_error:
                retried_for_context = True
                retry_budget_prompt = (
                    context_budget_prompt()
                    + "\n\n"
                    + article_typography_prompt(article_typography_settings)
                    + _layout_reference_context_prompt(layout_reference)
                )
                retry_builder = AgentContextBuilder(
                    stream_db,
                    document_id,
                    session_id,
                    stream_model,
                    edit_session.workspace(),
                    history_rows,
                    retry_budget_prompt,
                    user_message,
                    selection_budget_context,
                    current_image_count=len(image_attachment_ids),
                    budget_multiplier=0.5,
                    exclude_message_id=user_message_id,
                    model_call_tracker_factory=lambda: ModelCallTracker(
                        model_id=model_id,
                        user_id=user_id,
                        source=ModelCallSource.AGENT_CONTEXT_COMPACTION,
                        source_id=run_id,
                    ),
                )
                await agent_run_manager.publish(
                    run_id,
                    "context_stats",
                    {**retry_builder.snapshot(), "state": "retrying_after_provider_limit"},
                )
                prepared_context = await retry_builder.prepare(compaction_model)
                fallback_data = claim_thinking_capability_fallback_data(model_id, compaction_model)
                if fallback_data is not None:
                    await agent_run_manager.publish(run_id, "thinking_capability_fallback", fallback_data)
                await agent_run_manager.publish(run_id, "context_stats", prepared_context.stats)
                # Preparing a retry may read/write its snapshot. Do not leave
                # that transaction open during the next provider stream.
                stream_db.rollback()
                continue
            break

        if not completed:
            raise RuntimeError("Agent 未返回完成事件")
    except asyncio.CancelledError:
        logger.warning("agent_trace run=%s execution_cancelled", run_id)
        try:
            terminal_data = persist_terminal(
                AgentRunStatus.CANCELLED,
                partial_content("已停止本轮操作。"),
                context_events=terminal_context_events,
            )
        except Exception as persist_exc:  # noqa: BLE001 - SSE still needs a terminal event.
            logger.exception("agent_trace run=%s cancellation_persist_failed detail=%s", run_id, persist_exc)
            terminal_data = fallback_terminal_data(
                AgentRunStatus.CANCELLED,
                partial_content("已停止本轮操作，终态保存暂时不可用，未能确认修改是否已保存。"),
                str(persist_exc),
            )
        await agent_run_manager.publish(run_id, "final", terminal_data)
        await agent_run_manager.mark_terminal(run_id, terminal_data["run_status"])
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "Agent 执行失败"
        public_message = _agent_execution_error_message(message)
        logger.exception("agent_trace run=%s execution_failed detail=%s", run_id, message)
        try:
            terminal_data = persist_terminal(
                AgentRunStatus.FAILED,
                partial_content(public_message),
                error_message=message,
                compliance=terminal_compliance,
                context_events=terminal_context_events,
            )
        except Exception as persist_exc:  # noqa: BLE001 - never leave the browser in running state.
            logger.exception("agent_trace run=%s failure_persist_failed detail=%s", run_id, persist_exc)
            terminal_data = fallback_terminal_data(
                AgentRunStatus.FAILED,
                partial_content("本轮执行未完成，终态保存暂时不可用，未能确认修改是否已保存。"),
                f"{message}; 终态保存失败: {persist_exc}",
            )
        await agent_run_manager.publish(run_id, "error", {"message": public_message})
        await agent_run_manager.publish(run_id, "final", terminal_data)
        await agent_run_manager.mark_terminal(run_id, terminal_data["run_status"])
        logger.warning("agent_trace run=%s failure_terminal_marked status=%s", run_id, terminal_data["run_status"])
    finally:
        stream_db.close()
        log_process_memory(
            logger,
            stage="agent_end",
            worker_id=agent_run_manager.worker_id,
            run_id=run_id,
        )
        logger.warning("agent_trace run=%s execution_closed", run_id)
