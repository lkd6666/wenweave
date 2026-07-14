"""可取消、可重连的 HTML 编辑 Agent 接口。"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from time import perf_counter
from typing import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.ai_model import AIModel
from app.models.chat_message import ChatMessage, MessageRole
from app.models.document import Document
from app.models.document_version import DocumentVersionSource
from app.models.user import User
from app.schemas.chat import AgentRunRead, ChatContextStatsRead, ChatMessageRead, ChatSendRequest
from app.services.agent_run_manager import TERMINAL_STATUSES, agent_run_manager
from app.services.agent_context import AgentContextBuilder
from app.services.chat_agent import HtmlEditSession, build_chat_model, context_budget_prompt, run_agent_loop
from app.services.document_activity import touch_document, touch_group
from app.services.document_access import can_access_document
from app.services.document_versions import create_document_version
from app.services.layout_reference import LayoutReferenceError, layout_reference_cache
from app.services.model_access import can_access_model
from app.services.token_budget import truncate_to_tokens
from app.services.wechat_compliance import run_compliance_check

router = APIRouter(prefix="/api/documents", tags=["chat"])

ACTIVE_RUN_STATUSES = {
    AgentRunStatus.PENDING,
    AgentRunStatus.RUNNING,
    AgentRunStatus.CANCELLING,
}
settings = get_settings()
AGENT_EVENT_IDLE_TIMEOUT_SECONDS = settings.CHAT_AGENT_EVENT_IDLE_TIMEOUT_SECONDS
AGENT_MAX_RUNTIME_SECONDS = settings.CHAT_AGENT_MAX_RUNTIME_SECONDS
CONTEXT_LIMIT_ERROR_PATTERN = re.compile(
    r"context(?:[_ -]?length)?|maximum context|input.*too (?:long|large)|too many tokens|token limit",
    re.IGNORECASE,
)


def _is_context_limit_error(message: str) -> bool:
    return bool(CONTEXT_LIMIT_ERROR_PATTERN.search(message))


def _get_accessible_document(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if not document or not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return document


def _run_read(run: AgentRun) -> AgentRunRead:
    return AgentRunRead(
        run_id=run.id,
        status=run.status,
        user_message_id=run.user_message_id,
        assistant_message_id=run.assistant_message_id,
        error_message=run.error_message,
    )


def _settle_terminal_timeline(tool_calls: list[dict], turn_blocks: list[dict]) -> bool:
    """Ensure a persisted assistant message never retains a live tool state."""
    changed = False

    def settle_tool(tool: dict) -> None:
        nonlocal changed
        if tool.get("status") != "running":
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
        if block.get("state") == "active":
            block["state"] = "done"
            block.pop("_started_at", None)
            changed = True
        tool = block.get("tool")
        if isinstance(tool, dict):
            settle_tool(tool)
    return changed


def _settle_persisted_assistant_message(message: ChatMessage) -> bool:
    tool_calls = message.tool_calls
    turn_blocks = message.turn_blocks
    if not _settle_terminal_timeline(tool_calls, turn_blocks):
        return False
    message.tool_calls_json = json.dumps(tool_calls, ensure_ascii=False)
    message.turn_blocks_json = json.dumps(turn_blocks, ensure_ascii=False)
    return True


def _persist_restart_failure(db: Session, run: AgentRun, document: Document) -> None:
    """Store a visible assistant result when an in-memory run disappeared after restart."""
    if run.assistant_message_id:
        return
    content = run.error_message or "服务已重启，未完成的 Agent 已停止；请重新执行本轮操作"
    assistant_message = ChatMessage(document_id=document.id, role=MessageRole.ASSISTANT, content=content)
    db.add(assistant_message)
    db.flush()
    run.assistant_message_id = assistant_message.id
    run.finished_at = run.finished_at or datetime.now(timezone.utc)


@router.get("/{document_id}/messages", response_model=list[ChatMessageRead])
def list_messages(
    document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ChatMessage]:
    document = _get_accessible_document(db, document_id, current_user)
    orphaned_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.document_id == document.id,
            AgentRun.user_id == current_user.id,
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
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.document_id == document_id, ChatMessage.is_superseded.is_(False))
        .order_by(ChatMessage.id)
        .all()
    )
    for item in messages:
        if item.role == MessageRole.ASSISTANT:
            changed = _settle_persisted_assistant_message(item) or changed
    if changed:
        db.commit()
    return messages


@router.get("/{document_id}/chat-context", response_model=ChatContextStatsRead)
def get_chat_context(
    document_id: int,
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_accessible_document(db, document_id, current_user)
    model = db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该模型的权限")
    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.document_id == document.id, ChatMessage.is_superseded.is_(False))
        .order_by(ChatMessage.id)
        .all()
    )
    builder = AgentContextBuilder(
        db,
        document.id,
        model,
        HtmlEditSession(document.current_html, model.tool_result_max_tokens).workspace(),
        history_rows,
        context_budget_prompt(),
    )
    return builder.snapshot()


@router.get("/{document_id}/chat-runs/active", response_model=AgentRunRead | None)
def get_active_run(
    document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AgentRunRead | None:
    _get_accessible_document(db, document_id, current_user)
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.document_id == document_id,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .order_by(AgentRun.created_at.desc())
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
    run = db.get(AgentRun, run_id)
    if not run or run.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="执行记录不存在")
    if run.status == AgentRunStatus.FAILED and not run.assistant_message_id:
        _persist_restart_failure(db, run, document)
        db.commit()
    return _run_read(run)


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
        return _run_read(existing)

    active_run = (
        db.query(AgentRun)
        .filter(
            AgentRun.document_id == document.id,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .first()
    )
    if active_run:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前推文已有正在执行的 Agent，请等待完成或先停止")

    model = db.get(AIModel, payload.model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    if not can_access_model(current_user, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有使用该模型的权限，请联系管理员")
    if not payload.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息内容不能为空")
    layout_reference: dict | None = None
    if payload.layout_reference_id:
        try:
            layout_reference = layout_reference_cache.get(payload.layout_reference_id, current_user.id).agent_payload()
        except LayoutReferenceError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Reference HTML is external, transient input. Allocate it from the
    # selected model's active budget before it reaches either the estimator or
    # the model, rather than relying on a process-wide character limit.
    if layout_reference:
        layout_reference = {
            **layout_reference,
            "html": truncate_to_tokens(
                str(layout_reference.get("html", "")),
                max(1, int(model.context_compaction_threshold_tokens) // 2),
            ),
        }
    selected_elements = [element.model_dump() for element in payload.selected_elements]
    reference_budget_prompt = context_budget_prompt()
    if layout_reference:
        reference_budget_prompt += "\n\n外部排版参考：\n" + str(layout_reference.get("html", ""))
    selection_budget_context = json.dumps(selected_elements, ensure_ascii=False) if selected_elements else ""
    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.document_id == document.id, ChatMessage.is_superseded.is_(False))
        .order_by(ChatMessage.id)
        .all()
    )
    preflight = AgentContextBuilder(
        db,
        document.id,
        model,
        HtmlEditSession(document.current_html, model.tool_result_max_tokens).workspace(),
        history_rows,
        reference_budget_prompt,
        payload.message,
        selection_budget_context,
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
        model.provider, model, payload.thinking_mode, payload.thinking_effort
    )
    compaction_model, _ = build_chat_model(
        model.provider,
        model,
        "disabled",
    )
    user_message = ChatMessage(
        document_id=document.id,
        role=MessageRole.USER,
        content=payload.message,
        selected_elements_json=json.dumps(selected_elements, ensure_ascii=False) if selected_elements else "[]",
        html_before=document.current_html,
    )
    db.add(user_message)
    db.flush()

    run = AgentRun(
        id=str(uuid4()),
        document_id=document.id,
        user_id=current_user.id,
        user_message_id=user_message.id,
        client_request_id=payload.client_request_id,
        status=AgentRunStatus.PENDING,
    )
    db.add(run)
    db.commit()

    agent_run_manager.create(run.id)
    task = asyncio.create_task(
        _execute_agent_run(
            run_id=run.id,
            document_id=document.id,
            user_id=current_user.id,
            chat_model=chat_model,
            thinking_status=thinking_status,
            document_title=document.title,
            current_html=document.current_html,
            user_message=payload.message,
            user_message_id=user_message.id,
            model_id=model.id,
            compaction_model=compaction_model,
            selected_elements=selected_elements,
            layout_reference=layout_reference,
        )
    )
    agent_run_manager.set_task(run.id, task)
    return _run_read(run)


@router.post("/{document_id}/chat-runs/{run_id}/cancel", response_model=AgentRunRead)
async def cancel_chat_run(
    document_id: int,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunRead:
    _get_accessible_document(db, document_id, current_user)
    run = db.get(AgentRun, run_id)
    if not run or run.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="执行记录不存在")
    if run.status in {AgentRunStatus.COMPLETED, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}:
        return _run_read(run)

    run.status = AgentRunStatus.CANCELLING
    db.commit()
    agent_run_manager.request_cancel(run_id)
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

    live_run = agent_run_manager.get(run_id)
    changed = False
    if not live_run and run.status in ACTIVE_RUN_STATUSES:
        # 进程已重启，无法安全地从中间的模型工具循环恢复；明确收尾，保留已有消息。
        run.status = AgentRunStatus.FAILED
        run.error_message = "服务已重启，未完成的 Agent 已停止；请重新执行本轮操作"
        run.finished_at = datetime.now(timezone.utc)
        changed = True
    if not live_run and run.status == AgentRunStatus.FAILED:
        _persist_restart_failure(db, run, document)
        changed = True
    if changed:
        db.commit()

    async def event_generator():
        if not live_run:
            if run.status == AgentRunStatus.FAILED:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": run.error_message}, ensure_ascii=False),
                }
                yield {
                    "event": "final",
                    "data": json.dumps(
                        {
                            "content": run.error_message,
                            "html": document.current_html,
                            "html_changed": False,
                            "compliance": run_compliance_check(document.current_html).to_dict(),
                            "partial": True,
                        },
                        ensure_ascii=False,
                    ),
                }
            return
        async for item in agent_run_manager.events_after(run_id, after):
            event = {
                "event": item.event,
                "data": json.dumps(item.data, ensure_ascii=False),
            }
            if item.sequence > 0:
                event["id"] = str(item.sequence)
            yield event

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def _iterate_agent_events_with_timeout(events: AsyncIterator[dict]) -> AsyncIterator[dict]:
    """Guard silent provider stalls without treating streamed tool arguments as idle."""
    iterator = events.__aiter__()
    started_at = perf_counter()
    try:
        while True:
            elapsed = perf_counter() - started_at
            remaining = AGENT_MAX_RUNTIME_SECONDS - elapsed
            if remaining <= 0:
                raise RuntimeError(
                    f"Agent 运行超过 {AGENT_MAX_RUNTIME_SECONDS} 秒总时限，已停止本轮执行"
                )
            try:
                yield await asyncio.wait_for(
                    iterator.__anext__(), timeout=min(AGENT_EVENT_IDLE_TIMEOUT_SECONDS, remaining)
                )
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                if perf_counter() - started_at >= AGENT_MAX_RUNTIME_SECONDS:
                    raise RuntimeError(
                        f"Agent 运行超过 {AGENT_MAX_RUNTIME_SECONDS} 秒总时限，已停止本轮执行"
                    ) from exc
                raise RuntimeError(
                    f"Agent 连续 {AGENT_EVENT_IDLE_TIMEOUT_SECONDS} 秒没有产生任何输出或工具事件，已停止本轮执行"
                ) from exc
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose:
            await aclose()


async def _execute_agent_run(
    *,
    run_id: str,
    document_id: int,
    user_id: int,
    chat_model,
    thinking_status,
    document_title: str,
    current_html: str,
    user_message: str,
    user_message_id: int,
    model_id: int,
    compaction_model,
    selected_elements: list[dict],
    layout_reference: dict | None = None,
) -> None:
    """独立于浏览器 SSE 的执行任务；任何终态均保存已完成过程。"""
    stream_db = SessionLocal()
    tool_trace: list[dict] = []
    turn_blocks: list[dict] = []
    reasoning_parts: list[str] = []
    reasoning_status = "idle"
    reasoning_detail = ""
    latest_html = current_html

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

    def persist_terminal(
        terminal_status: AgentRunStatus,
        content: str,
        *,
        error_message: str = "",
        compliance: dict | None = None,
    ) -> dict:
        finish_active_text_block()
        _settle_terminal_timeline(tool_trace, turn_blocks)
        nonlocal reasoning_status, reasoning_detail
        if reasoning_parts:
            reasoning_status = "complete"
        elif thinking_status.requested == "enabled" and not thinking_status.applied:
            reasoning_status = "unavailable"
            reasoning_detail = thinking_status.detail
        elif thinking_status.requested == "enabled":
            reasoning_status = "unavailable"
            reasoning_detail = "模型未返回可展示的思考内容"

        document = (
            stream_db.query(Document)
            .filter(Document.id == document_id)
            .with_for_update()
            .first()
        )
        document_conflict = bool(document and document.current_html != current_html)
        if document_conflict:
            terminal_status = AgentRunStatus.FAILED
            error_message = error_message or "运行期间文档已被手动或外部修改，Agent 结果未覆盖该修改"
            content = f"{content}\n\n检测到文档在运行期间发生了其他修改，未覆盖当前内容。"

        html_changed = latest_html != current_html and not document_conflict
        if document and html_changed:
            document.current_html = latest_html
            touch_document(document, user_id)
            if document.group:
                touch_group(document.group, user_id)

        assistant_message = ChatMessage(
            document_id=document_id,
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
        stream_db.add(assistant_message)
        stream_db.flush()
        if document and html_changed:
            label = "AI 编辑" if terminal_status == AgentRunStatus.COMPLETED else "AI 编辑（未完成）"
            create_document_version(stream_db, document, user_id, DocumentVersionSource.AI, label)

        run = stream_db.get(AgentRun, run_id)
        if run:
            run.status = terminal_status
            run.error_message = error_message
            run.assistant_message_id = assistant_message.id
            run.finished_at = datetime.now(timezone.utc)
        stream_db.commit()
        report_html = document.current_html if document_conflict and document else latest_html
        return {
            "content": content,
            "html": report_html,
            "html_changed": html_changed,
            "compliance": compliance if compliance and not document_conflict else run_compliance_check(report_html).to_dict(),
            "cancelled": terminal_status == AgentRunStatus.CANCELLED,
            "partial": terminal_status != AgentRunStatus.COMPLETED,
            "run_status": terminal_status.value,
            "error_message": error_message,
        }

    try:
        cancelled_before_start = agent_run_manager.mark_started(run_id)
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
                ChatMessage.id != user_message_id,
                ChatMessage.is_superseded.is_(False),
            )
            .order_by(ChatMessage.id)
            .all()
        )
        session = HtmlEditSession(current_html, stream_model.tool_result_max_tokens)
        budget_prompt = context_budget_prompt()
        if layout_reference:
            # The reference is current-turn context, not durable memory, but it
            # still consumes the selected model's input budget.
            budget_prompt += "\n\n外部排版参考：\n" + str(layout_reference.get("html", ""))
        selection_budget_context = json.dumps(selected_elements, ensure_ascii=False) if selected_elements else ""
        context_builder = AgentContextBuilder(
            stream_db,
            document_id,
            stream_model,
            session.workspace(),
            history_rows,
            budget_prompt,
            user_message,
            selection_budget_context,
        )
        await agent_run_manager.publish(run_id, "context_stats", {**context_builder.snapshot(), "state": "preparing"})
        prepared_context = await context_builder.prepare(compaction_model)
        await agent_run_manager.publish(run_id, "context_stats", prepared_context.stats)
        if layout_reference:
            reference_tool = {
                "id": "layout-reference",
                "name": "apply_layout_reference",
                "arguments": {"url": layout_reference.get("canonical_url", "")},
                "status": "success",
                "result": "已载入参考排版，将保留当前文案和图片，仅模仿视觉结构。",
                "html_changed": False,
                "activity": {"kind": "reference", "summary": "已载入参考排版"},
            }
            tool_trace.append(reference_tool)
            turn_blocks.append({"id": "block-layout-reference", "type": "tool", "state": "done", "tool": reference_tool})
            await agent_run_manager.publish(
                run_id,
                "tool_call",
                {"id": reference_tool["id"], "name": reference_tool["name"], "arguments": reference_tool["arguments"]},
            )
            await agent_run_manager.publish(
                run_id,
                "tool_result",
                {"name": reference_tool["name"], "result": reference_tool["result"], "activity": reference_tool["activity"]},
            )
        completed = False
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
                    session,
                )
            ):
                event = evt["event"]
                data = evt["data"]
                if event == "reasoning_delta":
                    reasoning_text = data.get("text", "")
                    reasoning_parts.append(reasoning_text)
                    append_text_block("thought", reasoning_text)
                    reasoning_status = "thinking"
                elif event == "text_delta":
                    append_text_block("content", data.get("text", ""))
                elif event == "tool_call":
                    finish_active_text_block()
                    tool_id = str(data.get("id") or f"tool-{len(tool_trace) + 1}")
                    existing_tool = next((item for item in tool_trace if item["id"] == tool_id), None)
                    if existing_tool:
                        existing_tool["name"] = data.get("name", existing_tool["name"])
                        existing_tool["arguments"] = data.get("arguments", existing_tool["arguments"])
                        if not data.get("preparing"):
                            existing_tool["preparing"] = False
                    else:
                        tool_entry = {
                            "id": tool_id,
                            "name": data.get("name", "unknown"),
                            "arguments": data.get("arguments", {}),
                            "status": "running",
                            "preparing": bool(data.get("preparing")),
                            "result": None,
                            "html_changed": False,
                            "activity": None,
                        }
                        tool_trace.append(tool_entry)
                        turn_blocks.append(
                            {"id": f"block-{tool_entry['id']}", "type": "tool", "state": "done", "tool": tool_entry}
                        )
                elif event == "tool_result":
                    for item in reversed(tool_trace):
                        if item["name"] == data.get("name") and item["status"] == "running":
                            item["result"] = data.get("result", "")
                            item["status"] = "error" if str(data.get("result", "")).startswith("错误") else "success"
                            item["preparing"] = False
                            item["html_changed"] = bool(data.get("html"))
                            item["activity"] = data.get("activity")
                            break
                    if data.get("html"):
                        latest_html = data["html"]
                    else:
                        # Tool activity is intentionally payload-safe; the
                        # mutable session remains the source for partial
                        # persistence if the run is cancelled after an edit.
                        latest_html = session.html
                elif event == "error":
                    detail = str(data.get("message", "Agent 执行失败"))
                    # Retry only before a model response or tool mutation is
                    # visible. Replaying after an edit would risk duplicate
                    # writes and must remain a terminal failure.
                    if (
                        not retried_for_context
                        and not session.edited
                        and not reasoning_parts
                        and not any(block.get("type") == "content" and block.get("content") for block in turn_blocks)
                        and _is_context_limit_error(detail)
                    ):
                        context_error = detail
                        break
                    raise RuntimeError(detail)
                elif event == "final":
                    latest_html = data.get("html") or latest_html
                    terminal_data = persist_terminal(
                        AgentRunStatus.COMPLETED,
                        data.get("content") or "已完成本轮编辑。",
                        compliance=data.get("compliance"),
                    )
                    await agent_run_manager.publish(run_id, "final", terminal_data)
                    await agent_run_manager.mark_terminal(run_id, terminal_data["run_status"])
                    completed = True
                    break

                await agent_run_manager.publish(run_id, event, data)

            if context_error:
                retried_for_context = True
                retry_budget_prompt = context_budget_prompt()
                if layout_reference:
                    active_layout_reference = {
                        **layout_reference,
                        "html": truncate_to_tokens(
                            str(layout_reference.get("html", "")),
                            max(1, int(stream_model.context_compaction_threshold_tokens) // 4),
                        ),
                    }
                    retry_budget_prompt += "\n\n外部排版参考：\n" + str(active_layout_reference["html"])
                retry_builder = AgentContextBuilder(
                    stream_db,
                    document_id,
                    stream_model,
                    session.workspace(),
                    history_rows,
                    retry_budget_prompt,
                    user_message,
                    selection_budget_context,
                    budget_multiplier=0.5,
                )
                await agent_run_manager.publish(
                    run_id,
                    "context_stats",
                    {**retry_builder.snapshot(), "state": "retrying_after_provider_limit"},
                )
                prepared_context = await retry_builder.prepare(compaction_model)
                await agent_run_manager.publish(run_id, "context_stats", prepared_context.stats)
                continue
            break

        if not completed:
            raise RuntimeError("Agent 未返回完成事件")
    except asyncio.CancelledError:
        terminal_data = persist_terminal(
            AgentRunStatus.CANCELLED,
            partial_content("已停止本轮操作，已保留已完成的修改。"),
        )
        await agent_run_manager.publish(run_id, "final", terminal_data)
        await agent_run_manager.mark_terminal(run_id, terminal_data["run_status"])
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "Agent 执行失败"
        terminal_data = persist_terminal(
            AgentRunStatus.FAILED,
            partial_content("本轮执行未完成，已保留已完成的修改。"),
            error_message=message,
        )
        await agent_run_manager.publish(run_id, "error", {"message": f"Agent 执行失败: {message}"})
        await agent_run_manager.publish(run_id, "final", terminal_data)
        await agent_run_manager.mark_terminal(run_id, terminal_data["run_status"])
    finally:
        stream_db.close()
