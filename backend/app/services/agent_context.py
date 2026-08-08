"""Durable, provider-visible context construction for the HTML editing Agent."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.ai_model import AIModel
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_history_archive import ChatHistoryArchive
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession, ChatSessionMemory
from app.services.html_workspace import HtmlWorkspace
from app.services.chat_images import CHAT_IMAGE_TOKEN_COST, attachment_text_suffix, image_content_blocks
from app.services.token_budget import estimate_tokens, truncate_to_tokens
from app.services.tool_output_store import tool_output_stats
from app.services.model_call_accounting import ModelCallTracker

COMPACTION_TRIGGER_RATIO = 0.90
COMPACTION_TARGET_TOKENS = 20_000
DEFAULT_PRESERVE_RECENT_TOKENS = 20_000
# Compaction is a small, single-purpose model turn. It uses an independent
# client configuration with no SDK retry, so an upstream 5xx cannot turn into
# several minutes of hidden retries before the run fails. Two explicit
# attempts still give slower providers enough time to respond.  The outer
# coroutine timeout and the HTTP request timeout must stay aligned; otherwise
# the client would still fail before the advertised compaction timeout.
COMPACTION_MODEL_TIMEOUT_SECONDS = 300
COMPACTION_MODEL_REQUEST_TIMEOUT_SECONDS = 300
COMPACTION_MODEL_MAX_RETRIES = 0
COMPACTION_MODEL_MAX_OUTPUT_TOKENS = 12_000
# The same tools are bound for every editor turn. This conservative schema
# reserve keeps preflight below provider limits even when a provider adds JSON
# envelope tokens that tiktoken cannot see.
AGENT_TOOL_SCHEMA_RESERVE_TOKENS = 3_500
MEMORY_ITEM_LIMIT = 12
MEMORY_ITEM_MAX_CHARS = 360
MEMORY_OBJECTIVE_MAX_CHARS = 900
MEMORY_NARRATIVE_MAX_CHARS = 1_800
SOURCE_REF_ITEM_LIMIT = 32
SOURCE_REF_PATTERN = re.compile(
    r"^(?:event:\d+|tool:toolout-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
CURRENT_DOCUMENT_TOOL_NAMES = {
    "get_document_map",
    "search_html",
    "read_blocks",
    "apply_html_patch",
    "replace_document",
    "inspect_current_images",
    "check_compliance",
}


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            item if isinstance(item, str) else str(item.get("text", ""))
            for item in value
            if isinstance(item, (str, dict))
        )
    return ""


def _short(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else f"{value[: max(0, limit - 1)]}…"


def _tool_summary(tools: Any, max_tokens: int) -> str:
    """Render legacy display-tool records without reviving stale locators.

    Context replay now uses :class:`ChatContextEvent`, but a few integrations
    still use this helper for read-only presentation.  Keep it deliberately
    semantic: document revisions and block IDs become invalid after an edit,
    while tool names, status, activity summaries, and edited text remain
    useful clues for a later ``search_html`` call.
    """
    if not isinstance(tools, list) or max_tokens <= 0:
        return ""

    lines: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name", "unknown"))
        status = str(tool.get("status", "success"))
        details: list[str] = []
        activity = tool.get("activity")
        if isinstance(activity, dict):
            summary = activity.get("summary")
            if isinstance(summary, str) and summary.strip():
                details.append(_short(summary, 360))
            targets = activity.get("targets")
            if isinstance(targets, list):
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    before = target.get("before")
                    after = target.get("after")
                    if isinstance(before, str) and isinstance(after, str):
                        details.append(f"更新文本：{_short(before, 180)} -> {_short(after, 180)}")
        result = tool.get("result")
        if isinstance(result, str) and result.strip():
            details.append(_short(result, 420))
        line = f"{name} [{status}]"
        if details:
            line += "：" + "；".join(details)
        lines.append(line)

    return truncate_to_tokens("\n".join(lines), max_tokens)


def _safe_json(value: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, dict) else fallback


def _normalise_memory(value: dict[str, Any]) -> dict[str, Any]:
    def values(key: str) -> list[str]:
        raw = value.get(key, [])
        if not isinstance(raw, list):
            raw = [raw]
        result: list[str] = []
        for item in raw:
            if isinstance(item, str):
                item = _short(item, MEMORY_ITEM_MAX_CHARS)
                if item and item not in result:
                    result.append(item)
        return result[-MEMORY_ITEM_LIMIT:]

    def refs() -> list[str]:
        raw = value.get("source_refs", [])
        raw = raw if isinstance(raw, list) else [raw]
        result: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            candidate = item.strip()
            if SOURCE_REF_PATTERN.fullmatch(candidate) and candidate not in result:
                result.append(candidate)
        return result[-SOURCE_REF_ITEM_LIMIT:]

    def text(key: str, limit: int = MEMORY_NARRATIVE_MAX_CHARS) -> str:
        return _short(str(value.get(key, "")), limit)

    return {
        "objective": text("objective", MEMORY_OBJECTIVE_MAX_CHARS),
        "important_details": values("important_details"),
        "user_preferences": values("user_preferences"),
        "completed_intents": values("completed_intents"),
        "active_work": values("active_work"),
        "pending_tasks": values("pending_tasks"),
        "blocked": values("blocked"),
        "next_move": values("next_move"),
        "relevant_files": values("relevant_files"),
        "source_refs": refs(),
        "narrative": text("narrative"),
    }


def _fit_memory_to_budget(value: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    """Keep the durable summary within the space reserved for it."""
    memory = _normalise_memory(value)
    max_tokens = max(1, int(max_tokens))

    def used_tokens() -> int:
        return estimate_tokens(json.dumps(memory, ensure_ascii=False))

    if used_tokens() <= max_tokens:
        return memory

    # Preserve the active objective and unresolved work longest; the remaining
    # entries are ordered from least to most useful when space is scarce.
    for key in (
        "completed_intents",
        "relevant_files",
        "source_refs",
        "user_preferences",
        "important_details",
        "blocked",
        "next_move",
        "active_work",
        "pending_tasks",
    ):
        while memory[key] and used_tokens() > max_tokens:
            memory[key].pop(0)

    if used_tokens() > max_tokens:
        memory["narrative"] = truncate_to_tokens(memory["narrative"], max(64, max_tokens // 3))
    if used_tokens() > max_tokens:
        memory["objective"] = truncate_to_tokens(memory["objective"], max(64, max_tokens // 2))
    if used_tokens() > max_tokens:
        memory["narrative"] = ""
    return memory


@dataclass(frozen=True)
class ContextRecord:
    id: int
    message_id: int | None
    kind: str
    payload: dict[str, Any]
    document_revision: str = ""
    is_legacy: bool = False
    image_attachments: tuple[ChatImageAttachment, ...] = ()

    @property
    def content(self) -> str:
        return _content_text(self.payload.get("content", ""))

    def _stale_tool_content(self, current_revision: str, result_limit_tokens: int) -> str:
        name = str(self.payload.get("name", "工具"))
        content = self.content
        if (
            current_revision
            and name in CURRENT_DOCUMENT_TOOL_NAMES
            and (self.is_legacy or (self.document_revision and self.document_revision != current_revision))
        ):
            return json.dumps(
                {
                    "stale": True,
                    "tool": name,
                    "next_step": "历史定位已过期；请读取当前文档地图或重新搜索后再修改。",
                },
                ensure_ascii=False,
            )
        return truncate_to_tokens(content, result_limit_tokens)

    def to_message(
        self,
        current_revision: str,
        result_limit_tokens: int,
        db: Session | None = None,
        provider_type: str = "openai_compatible",
        include_images: bool = False,
    ) -> BaseMessage:
        if self.kind == ContextEventKind.USER.value:
            suffix = attachment_text_suffix(self.image_attachments, include_images)
            if db is None or not self.image_attachments:
                return HumanMessage(content=self.content + suffix)
            blocks = image_content_blocks(
                db, self.image_attachments, provider_type=provider_type, include_images=include_images
            )
            return HumanMessage(content=[{"type": "text", "text": self.content + suffix}, *blocks] if blocks else self.content + suffix)
        if self.kind == ContextEventKind.TOOL.value:
            return ToolMessage(
                content=self._stale_tool_content(current_revision, result_limit_tokens),
                tool_call_id=str(self.payload.get("tool_call_id", "")),
                name=str(self.payload.get("name", "")) or None,
                status=str(self.payload.get("status", "success")),
            )
        calls = self.payload.get("tool_calls", [])
        calls = calls if isinstance(calls, list) else []
        normalised_calls = [
            {
                "id": str(call.get("id", "")),
                "name": str(call.get("name", "unknown")),
                "args": call.get("args", {}) if isinstance(call.get("args"), dict) else {},
            }
            for call in calls
            if isinstance(call, dict) and call.get("id")
        ]
        return AIMessage(content=self.content, tool_calls=normalised_calls)

    def compact_line(self) -> str:
        event_ref = f"event:{self.id}"
        if self.kind == ContextEventKind.USER.value:
            suffix = f"（含 {len(self.image_attachments)} 张图片）" if self.image_attachments else ""
            return f"[{event_ref}] 用户：{_short(self.content, 700)}{suffix}"
        if self.kind == ContextEventKind.ASSISTANT.value:
            calls = self.payload.get("tool_calls", [])
            names = [str(call.get("name", "工具")) for call in calls if isinstance(call, dict)]
            suffix = f"；调用工具：{'、'.join(names)}" if names else ""
            return f"[{event_ref}] 助手：{_short(self.content, 700)}{suffix}"
        output_ref = ""
        try:
            parsed = json.loads(self.content)
            output_id = parsed.get("output_id") if isinstance(parsed, dict) else None
            candidate = f"tool:{output_id}" if isinstance(output_id, str) else ""
            output_ref = f" [{candidate}]" if SOURCE_REF_PATTERN.fullmatch(candidate) else ""
        except (TypeError, json.JSONDecodeError):
            pass
        return f"[{event_ref}] 工具 {self.payload.get('name', 'unknown')}{output_ref}：{_short(self.content, 420)}"


def context_prefix_hash(records: Sequence[ContextRecord], count: int | None = None) -> str:
    """Hash the canonical provider-visible prefix, never UI-only trace data."""
    selected = records if count is None else records[: max(0, count)]
    payload = [
        {
            "id": record.id,
            "message_id": record.message_id,
            "kind": record.kind,
            "payload": record.payload,
            "document_revision": record.document_revision,
            "legacy": record.is_legacy,
        }
        for record in selected
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PreparedAgentContext:
    memory: dict[str, Any]
    history: list[BaseMessage]
    workspace_map: dict[str, Any]
    stats: dict[str, Any]


class ContextBudgetError(ValueError):
    """The configured input budget cannot hold required current context."""


class CompactionModelError(RuntimeError):
    """The no-tools compaction request failed without changing the ledger."""


def compaction_failure_detail(exc: BaseException | None) -> str:
    """Return an actionable public error without exposing provider tracebacks."""
    detail = str(exc or "").strip()
    normalized = detail.lower()
    if isinstance(exc, TimeoutError) or "timeout" in normalized or "timed out" in normalized:
        return f"压缩模型在 {COMPACTION_MODEL_TIMEOUT_SECONDS} 秒内未返回，可重试"
    if isinstance(exc, ValueError):
        return "压缩模型返回了无效摘要，可重试"
    match = re.search(r"\b(5\d\d)\b", detail)
    if match:
        return f"压缩模型服务暂时不可用（上游 {match.group(1)}），可重试"
    if detail:
        return f"压缩模型服务暂时不可用，可重试：{_short(detail, 180)}"
    return "压缩模型服务暂时不可用，可重试"


class AgentContextBuilder:
    """Build a Cline-style live transcript without replaying stale HTML state."""

    def __init__(
        self,
        db: Session,
        document_id: int,
        session_id: int,
        model: AIModel,
        workspace: HtmlWorkspace,
        history_rows: Sequence[ChatMessage],
        base_prompt: str,
        current_request: str = "",
        additional_context: str = "",
        current_image_count: int = 0,
        budget_multiplier: float = 1.0,
        exclude_message_id: int = 0,
        model_call_tracker_factory: Callable[[], ModelCallTracker] | None = None,
    ):
        self.db = db
        self.document_id = document_id
        self.session_id = session_id
        self.model = model
        self.workspace = workspace
        self.base_prompt = base_prompt
        self.current_request = current_request
        self.additional_context = additional_context
        self.current_image_count = max(0, int(current_image_count))
        self.exclude_message_id = exclude_message_id
        self.model_call_tracker_factory = model_call_tracker_factory
        self.budget_multiplier = min(1.0, max(0.35, budget_multiplier))
        self.window = int(model.context_window_tokens)
        self.max_output_tokens = int(model.max_output_tokens)
        self.usable_budget = int(model.context_compaction_threshold_tokens)
        self.trigger_budget = max(1, int(self.usable_budget * COMPACTION_TRIGGER_RATIO * self.budget_multiplier))
        # Keep a short, information-dense hot context after compaction. Larger
        # model windows should increase the distance between compactions, not
        # make each compacted transcript needlessly large.
        self.target_budget = min(self.usable_budget, COMPACTION_TARGET_TOKENS)
        self.memory_target_tokens = min(
            COMPACTION_MODEL_MAX_OUTPUT_TOKENS,
            self.max_output_tokens,
            max(1_024, self.target_budget // 4),
        )
        compactor_output_budget = min(self.max_output_tokens, COMPACTION_MODEL_MAX_OUTPUT_TOKENS)
        self.compaction_source_budget = max(
            1_024,
            min(self.usable_budget, self.window - compactor_output_budget - 2_048),
        )
        self.tool_result_max_tokens = int(model.tool_result_max_tokens)
        self.session = self.db.get(ChatSession, session_id)
        self.records = self._load_records(history_rows)

    def _load_records(self, history_rows: Sequence[ChatMessage]) -> list[ContextRecord]:
        query = (
            self.db.query(ChatContextEvent)
            # Every provider-visible event must have a concrete active message
            # owner.  A nullable FK is retained for old databases, but an
            # orphaned event has no provable branch membership after a re-ask
            # and must therefore stay in the raw ledger only.
            .join(ChatMessage, ChatContextEvent.message_id == ChatMessage.id)
            .filter(
                ChatContextEvent.document_id == self.document_id,
                ChatContextEvent.session_id == self.session_id,
                ChatMessage.document_id == self.document_id,
                ChatMessage.session_id == self.session_id,
                ChatMessage.is_superseded.is_(False),
            )
        )
        if self.session and self.session.context_start_message_id > 0:
            query = query.filter(ChatContextEvent.message_id > self.session.context_start_message_id)
        if self.exclude_message_id:
            query = query.filter(ChatContextEvent.message_id != self.exclude_message_id)
        events = query.order_by(ChatContextEvent.id).all()
        if events:
            message_ids = [event.message_id for event in events if event.message_id]
            attachment_map: dict[int, tuple[ChatImageAttachment, ...]] = {}
            if message_ids:
                attachments = (
                    self.db.query(ChatImageAttachment)
                    .filter(ChatImageAttachment.message_id.in_(message_ids))
                    .order_by(ChatImageAttachment.created_at)
                    .all()
                )
                grouped: dict[int, list[ChatImageAttachment]] = {}
                for attachment in attachments:
                    if attachment.message_id:
                        grouped.setdefault(attachment.message_id, []).append(attachment)
                attachment_map = {key: tuple(value) for key, value in grouped.items()}
            return [
                ContextRecord(
                    id=event.id,
                    message_id=event.message_id,
                    kind=event.kind.value if isinstance(event.kind, ContextEventKind) else str(event.kind),
                    payload=event.payload,
                    document_revision=event.document_revision,
                    is_legacy=event.is_legacy,
                    image_attachments=attachment_map.get(event.message_id or 0, ()),
                )
                for event in events
            ]

        # Unit tests and an interrupted migration may have chat rows before
        # their backfill. This read-only fallback preserves old behavior.
        records: list[ContextRecord] = []
        for row in history_rows:
            if not row.content.strip():
                continue
            kind = ContextEventKind.USER.value if row.role == MessageRole.USER else ContextEventKind.ASSISTANT.value
            records.append(
                ContextRecord(
                    row.id,
                    row.id,
                    kind,
                    {"content": row.content},
                    is_legacy=True,
                    image_attachments=tuple(row.image_attachments),
                )
            )
        return records

    def _source_records(self) -> list[ContextRecord]:
        return self._valid_records(self.records)

    def _checkpoint_is_valid(
        self, checkpoint: ChatContextSnapshot | ChatSessionMemory, source_records: Sequence[ContextRecord]
    ) -> bool:
        """Validate a snapshot against its immutable active-ledger prefix."""
        if isinstance(checkpoint, ChatContextSnapshot):
            source_count = int(checkpoint.source_event_count or 0)
            source_hash = str(checkpoint.source_prefix_hash or "")
            if source_count and source_hash:
                if not self.session or int(checkpoint.context_generation or 0) != int(self.session.context_generation or 0):
                    return False
                return source_count <= len(source_records) and context_prefix_hash(source_records, source_count) == source_hash

        # Older rows predate source anchors. Keep their timestamp check only
        # until bootstrap can backfill or invalidate them.
        checkpoint_at = getattr(checkpoint, "created_at", None) or getattr(checkpoint, "updated_at", None)
        covered_event_id = int(getattr(checkpoint, "compacted_through_event_id", 0) or 0)
        covered_message_id = int(getattr(checkpoint, "compacted_through_message_id", 0) or 0)
        if not covered_event_id and not covered_message_id:
            return True

        if covered_event_id:
            query = (
                self.db.query(ChatContextEvent.id)
                .join(ChatMessage, ChatContextEvent.message_id == ChatMessage.id)
                .filter(
                    ChatContextEvent.document_id == self.document_id,
                    ChatContextEvent.session_id == self.session_id,
                    ChatContextEvent.id <= covered_event_id,
                    ChatMessage.is_superseded.is_(True),
                )
            )
            source_start_event_id = int(getattr(checkpoint, "source_start_event_id", 0) or 0)
            if source_start_event_id:
                query = query.filter(ChatContextEvent.id >= source_start_event_id)
        else:
            query = self.db.query(ChatMessage.id).filter(
                ChatMessage.document_id == self.document_id,
                ChatMessage.session_id == self.session_id,
                ChatMessage.id <= covered_message_id,
                ChatMessage.is_superseded.is_(True),
            )
        if checkpoint_at is not None:
            query = query.filter(ChatMessage.superseded_at.is_not(None), ChatMessage.superseded_at >= checkpoint_at)
        return query.first() is None

    def _load_snapshot(self, source_records: Sequence[ContextRecord]) -> ChatContextSnapshot | None:
        snapshot = (
            self.db.query(ChatContextSnapshot)
            .filter(ChatContextSnapshot.session_id == self.session_id, ChatContextSnapshot.is_active.is_(True))
            .order_by(ChatContextSnapshot.id.desc())
            .first()
        )
        if snapshot and not self._checkpoint_is_valid(snapshot, source_records):
            snapshot.is_active = False
            snapshot.active_slot = None
            snapshot.invalidation_reason = "source_diverged"
            self.db.flush()
            return None
        if snapshot is None:
            # Older releases lazily invalidated snapshots using only a message
            # ID. Recover the newest such snapshot once when the timestamped
            # source check proves it is still valid. Explicit invalidations are
            # never revived.
            recoverable = (
                self.db.query(ChatContextSnapshot)
                .filter(
                    ChatContextSnapshot.session_id == self.session_id,
                    ChatContextSnapshot.is_active.is_(False),
                    ChatContextSnapshot.invalidation_reason == "",
                )
                .order_by(ChatContextSnapshot.id.desc())
                .first()
            )
            if recoverable and self._checkpoint_is_valid(recoverable, source_records):
                recoverable.is_active = True
                recoverable.active_slot = 1
                self.db.flush()
                return recoverable
        return snapshot

    def _load_memory(self, source_records: Sequence[ContextRecord]) -> ChatSessionMemory | None:
        memory = self.db.query(ChatSessionMemory).filter(ChatSessionMemory.session_id == self.session_id).first()
        if not memory:
            return None
        if not self._checkpoint_is_valid(memory, source_records):
            memory.compacted_through_message_id = 0
            memory.compacted_through_event_id = 0
            memory.compaction_strategy = ""
            memory.summary_json = "{}"
            self.db.flush()
        return memory

    def _checkpoint(self, source_records: Sequence[ContextRecord]) -> ChatContextSnapshot | ChatSessionMemory | None:
        return self._load_snapshot(source_records) or self._load_memory(source_records)

    def _covered_id(self, checkpoint: ChatContextSnapshot | ChatSessionMemory | None) -> int:
        if not checkpoint:
            return 0
        return int(checkpoint.compacted_through_event_id or checkpoint.compacted_through_message_id or 0)

    def _records_after_checkpoint(
        self, source_records: Sequence[ContextRecord], checkpoint: ChatContextSnapshot | ChatSessionMemory | None
    ) -> list[ContextRecord]:
        if isinstance(checkpoint, ChatContextSnapshot) and checkpoint.source_event_count and checkpoint.source_prefix_hash:
            return list(source_records[int(checkpoint.source_event_count) :])
        return [record for record in source_records if record.id > self._covered_id(checkpoint)]

    def _render_map(self) -> str:
        entries = []
        map_limit = max(18, int(72 * self.budget_multiplier))
        for block in self.workspace.map_payload(map_limit)["blocks"]:
            label = " / ".join(block["heading_path"][-2:]) or block["tag"]
            flags = ", ".join(flag for flag, active in (("图片", block["has_image"]), ("表格", block["has_table"])) if active)
            entries.append(
                f"- {block['block_id']} | {label} | {block['path']} | {block['text'] or '无正文'}{(' | ' + flags) if flags else ''}"
            )
        return "\n".join(entries)

    def _record_tokens(self, record: ContextRecord) -> int:
        if record.kind == ContextEventKind.TOOL.value:
            return estimate_tokens(record._stale_tool_content(self.workspace.revision, self.tool_result_max_tokens))
        image_tokens = len(record.image_attachments) * CHAT_IMAGE_TOKEN_COST if self.model.is_multimodal else 0
        return estimate_tokens(json.dumps(record.payload, ensure_ascii=False)) + image_tokens

    def _valid_records(self, records: Sequence[ContextRecord]) -> list[ContextRecord]:
        """Drop incomplete persisted tool cycles before any provider sees them."""
        result: list[ContextRecord] = []
        index = 0
        while index < len(records):
            record = records[index]
            if record.kind != ContextEventKind.ASSISTANT.value:
                if record.kind != ContextEventKind.TOOL.value:
                    result.append(record)
                index += 1
                continue
            calls = record.payload.get("tool_calls", [])
            calls = calls if isinstance(calls, list) else []
            call_ids = {str(call.get("id")) for call in calls if isinstance(call, dict) and call.get("id")}
            has_duplicate_call_id = len(call_ids) != len(
                [call for call in calls if isinstance(call, dict) and call.get("id")]
            )
            if not call_ids:
                result.append(record)
                index += 1
                continue
            end = index + 1
            answered: set[str] = set()
            while end < len(records) and records[end].kind == ContextEventKind.TOOL.value:
                tool_id = str(records[end].payload.get("tool_call_id", ""))
                if tool_id in call_ids:
                    answered.add(tool_id)
                end += 1
            # A provider requires exactly one result for every tool call. A
            # duplicate or extra result is malformed too, even if every id
            # appears at least once.
            tool_ids = [str(records[item].payload.get("tool_call_id", "")) for item in range(index + 1, end)]
            if (
                not has_duplicate_call_id
                and answered == call_ids
                and len(tool_ids) == len(call_ids)
                and len(set(tool_ids)) == len(tool_ids)
            ):
                result.extend(records[index:end])
            index = end
        return result

    def _partition_for_compaction(
        self, records: Sequence[ContextRecord], memory: dict[str, Any]
    ) -> tuple[list[ContextRecord], list[ContextRecord]]:
        if not records:
            return [], []
        # Cline applies its preserved-tail limit to message budget after system
        # prompt and tool-schema overhead. Applying it to the whole request
        # would make a small-window model impossible to compact.
        fixed_overhead = (
            estimate_tokens(self.base_prompt)
            + estimate_tokens(self._render_map())
            + estimate_tokens(json.dumps(memory, ensure_ascii=False))
            + estimate_tokens(self.current_request)
            + estimate_tokens(self.additional_context)
            + AGENT_TOOL_SCHEMA_RESERVE_TOKENS
        )
        preserve = min(
            DEFAULT_PRESERVE_RECENT_TOKENS,
            max(1, self.target_budget - fixed_overhead - self.memory_target_tokens),
        )
        # Select the longest suffix that fits, but only at a user-turn start.
        # If even the newest historical turn is too large, summarize it too;
        # retaining a partial turn would either overflow the provider or split
        # a tool-call/result pair.
        boundaries = [
            index
            for index, record in enumerate(records)
            if index == 0 or record.kind == ContextEventKind.USER.value
        ]
        # The 20K target is deliberately soft. First prefer the longest
        # complete suffix that fits it; if even the newest turn is larger,
        # retain that legal turn when the actual input budget permits it.
        for start in boundaries:
            retained = records[start:]
            if sum(self._record_tokens(record) for record in retained) <= preserve:
                return list(records[:start]), list(retained)
        maximum_preserve = max(1, self.usable_budget - fixed_overhead - self.memory_target_tokens)
        for start in reversed(boundaries):
            retained = records[start:]
            if sum(self._record_tokens(record) for record in retained) <= maximum_preserve:
                return list(records[:start]), list(retained)
        return list(records), []

    def _stats(
        self,
        memory: dict[str, Any],
        replayed: Sequence[ContextRecord],
        state: str,
        checkpoint: ChatContextSnapshot | ChatSessionMemory | None,
    ) -> dict[str, Any]:
        map_tokens = estimate_tokens(self._render_map())
        system_tokens = estimate_tokens(self.base_prompt)
        memory_tokens = estimate_tokens(json.dumps(memory, ensure_ascii=False))
        replay_tokens = sum(self._record_tokens(record) for record in replayed)
        tool_tokens = sum(self._record_tokens(record) for record in replayed if record.kind == ContextEventKind.TOOL.value)
        current_image_tokens = self.current_image_count * CHAT_IMAGE_TOKEN_COST if self.model.is_multimodal else 0
        current_request_tokens = estimate_tokens(self.current_request) + current_image_tokens
        additional_context_tokens = estimate_tokens(self.additional_context)
        schema_tokens = AGENT_TOOL_SCHEMA_RESERVE_TOKENS
        used = system_tokens + map_tokens + memory_tokens + replay_tokens + current_request_tokens + additional_context_tokens + schema_tokens
        source_records = self._source_records()
        all_tokens = sum(self._record_tokens(record) for record in source_records) + current_request_tokens
        if isinstance(checkpoint, ChatContextSnapshot) and checkpoint.source_event_count and checkpoint.source_prefix_hash:
            compacted = source_records[: int(checkpoint.source_event_count)]
        else:
            covered = self._covered_id(checkpoint)
            compacted = [record for record in source_records if record.id <= covered]
        return {
            "used_tokens": used,
            "max_tokens": self.window,
            "usable_tokens": self.usable_budget,
            "usage_percent": min(100, round(used / max(1, self.usable_budget) * 100)),
            "is_estimate": True,
            "state": state,
            "breakdown": {
                "system": system_tokens,
                "document_map": map_tokens,
                "memory": memory_tokens,
                "recent_history": replay_tokens - tool_tokens,
                "tool_replay": tool_tokens,
                "tool_schema": schema_tokens,
                "current_request": current_request_tokens,
                "image_inputs": current_image_tokens,
                "selected_context": additional_context_tokens,
            },
            "tool_calls_count": sum(1 for record in source_records if record.kind == ContextEventKind.TOOL.value),
            "tool_summary_replayed_count": 0,
            "tool_compact_replayed_count": 0,
            "tool_full_replayed_count": sum(1 for record in replayed if record.kind == ContextEventKind.TOOL.value),
            "event_count": len(source_records),
            "replayed_event_count": len(replayed),
            "tokens_saved": max(0, all_tokens - sum(self._record_tokens(record) for record in replayed)),
            "conversation_tokens": all_tokens,
            "conversation_message_count": len(self.records) + (1 if current_request_tokens else 0),
            "compacted_history_tokens": sum(self._record_tokens(record) for record in compacted),
            "compacted_history_message_count": len(compacted),
            "compaction_strategy": (getattr(checkpoint, "strategy", "") or getattr(checkpoint, "compaction_strategy", "")) if checkpoint else "",
            "context_policy": "canonical_ledger + compiled_hot_context + model_compaction",
            "max_output_tokens": self.max_output_tokens,
            "tool_result_max_tokens": self.tool_result_max_tokens,
            "effective_tool_preview_tokens": self.tool_result_max_tokens,
            "budget_multiplier": self.budget_multiplier,
            "ledger_tokens": all_tokens,
            "compiled_input_tokens": used,
            "raw_input_tokens": used,
            "snapshot_id": int(getattr(checkpoint, "id", 0) or 0),
            "snapshot_source_event_count": int(getattr(checkpoint, "source_event_count", 0) or 0),
            "snapshot_prefix_valid": bool(checkpoint),
            "snapshot_covered_event_count": len(compacted),
            "cold_event_count": len(compacted),
            "hot_event_count": len(replayed),
            "archived_branch_count": self.db.query(ChatHistoryArchive.id).filter(
                ChatHistoryArchive.session_id == self.session_id
            ).count(),
            **tool_output_stats(self.db, self.session_id),
        }

    def snapshot(self) -> dict:
        source_records = self._source_records()
        checkpoint = self._checkpoint(source_records)
        memory = _fit_memory_to_budget(
            _safe_json(checkpoint.summary_json, {}) if checkpoint else {},
            self.memory_target_tokens,
        )
        active = self._records_after_checkpoint(source_records, checkpoint)
        active_stats = self._stats(memory, active, "ready", checkpoint)
        older, retained = self._partition_for_compaction(active, memory)
        # This is a prediction only. It never becomes durable unless the model
        # compactor succeeds in ``prepare``.
        projected_memory = self._deterministic_memory(memory, older) if older else memory
        projected_stats = self._stats(projected_memory, retained, "ready", checkpoint)
        requires_compaction = active_stats["used_tokens"] >= self.trigger_budget and bool(older)
        can_fit = projected_stats["used_tokens"] <= self.usable_budget
        state = "requires_compaction" if requires_compaction and can_fit else "ready"
        if active_stats["used_tokens"] > self.usable_budget and not can_fit:
            state = "context_overflow"
        # A projection derived from deterministic text must never be presented
        # as the next real model input.  Until the no-tools compactor succeeds,
        # the only truthful normal-request size is the active transcript.  The
        # predicted post-compaction size is kept separately for the warning.
        compiled_stats = active_stats
        return {
            **compiled_stats,
            "state": state,
            "requires_compaction": requires_compaction,
            "can_fit_after_compaction": can_fit,
            "overflow_tokens": max(0, active_stats["used_tokens"] - self.usable_budget),
            "projected_used_tokens": projected_stats["used_tokens"],
            "raw_input_tokens": active_stats["used_tokens"],
            "compiled_input_tokens": compiled_stats["used_tokens"],
            "ledger_tokens": active_stats["conversation_tokens"],
            "raw_breakdown": active_stats["breakdown"],
            "active_context_threshold_tokens": self.trigger_budget,
            "compaction_target_tokens": self.target_budget,
        }

    def _deterministic_memory(self, previous: dict[str, Any], older: Sequence[ContextRecord]) -> dict[str, Any]:
        next_memory = _normalise_memory(previous)
        for record in older:
            content = _short(record.content, 180)
            if not content:
                continue
            if record.kind == ContextEventKind.USER.value:
                bucket = next_memory["pending_tasks"] if any(word in content for word in ("继续", "还要", "请", "希望", "需要")) else next_memory["user_preferences"]
            elif record.kind == ContextEventKind.ASSISTANT.value:
                bucket = next_memory["completed_intents"]
            else:
                name = str(record.payload.get("name", "工具"))
                bucket = next_memory["completed_intents"]
                content = f"工具 {name}：{content}"
            if content not in bucket:
                bucket.append(content)
        for key in ("user_preferences", "completed_intents", "pending_tasks"):
            next_memory[key] = next_memory[key][-MEMORY_ITEM_LIMIT:]
        next_memory["narrative"] = _short("；".join(next_memory["completed_intents"][-4:]), 900)
        return _fit_memory_to_budget(next_memory, self.memory_target_tokens)

    async def _model_memory(
        self, chat_model: BaseChatModel, previous: dict[str, Any], older: Sequence[ContextRecord]
    ) -> dict[str, Any]:
        transcript = "\n".join(record.compact_line() for record in older)
        prompt = f"""将较早的排版 Agent 事件压缩为 JSON 工作记忆。当前 HTML、历史 block_id、revision、expected_hash 都不可靠，绝不能输出它们或源码。优先保留当前尚未完成的用户目标、不可违反的约束、已确认决策和下一步；与当前任务无关的旧主题、尝试过程和重复完成项应折叠或省略。

只返回一个 JSON 对象。字段固定为 objective、important_details、user_preferences、completed_intents、active_work、pending_tasks、blocked、next_move、relevant_files、source_refs、narrative。objective 必须描述当前待续接的实际任务，不能写“压缩历史”之类的元任务；narrative 为当前状态结论；其余字段为短字符串数组。摘要最多约 {self.memory_target_tokens} tokens。

source_refs 只能使用事件文本中明确出现的 event:<id>，或工具行中明确出现的 tool:toolout-<uuid>；禁止写工具名称、block_id、revision、猜测的 ID。没有精确引用时返回空数组。

已有记忆：
{json.dumps(previous, ensure_ascii=False)}

待压缩事件：
{truncate_to_tokens(transcript, self.compaction_source_budget)}"""
        last_error: Exception | None = None
        for attempt in range(2):
            tracker = self.model_call_tracker_factory() if self.model_call_tracker_factory else None
            try:
                response = await asyncio.wait_for(
                    chat_model.ainvoke(
                        [SystemMessage(content="你是安全的会话压缩器，只输出 JSON。"), HumanMessage(content=prompt)]
                    ),
                    timeout=COMPACTION_MODEL_TIMEOUT_SECONDS,
                )
                if tracker:
                    tracker.complete(response)
                text = _content_text(getattr(response, "content", ""))
                match = re.search(r"\{[\s\S]*\}", text)
                if not match:
                    raise ValueError("压缩模型没有返回 JSON")
                try:
                    value = json.loads(match.group(0))
                except json.JSONDecodeError as exc:
                    raise ValueError("压缩模型返回了无效 JSON") from exc
                required = ("objective", "important_details", "user_preferences", "completed_intents", "active_work", "pending_tasks", "blocked", "next_move", "relevant_files", "source_refs", "narrative")
                if (
                    not isinstance(value, dict)
                    or any(key not in value for key in required)
                    or any(not isinstance(value[key], list) for key in required[1:-1])
                    or not isinstance(value["objective"], str)
                    or not isinstance(value["narrative"], str)
                ):
                    raise ValueError("压缩模型返回的记忆结构无效")
                return _fit_memory_to_budget(value, self.memory_target_tokens)
            except Exception as exc:  # Preserve the raw ledger and retry the model once.
                if tracker:
                    tracker.fail(exc)
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.25)
        # Do not manufacture a rule-based summary. The durable snapshot is
        # written only after the model returned a valid structured result.
        raise CompactionModelError(compaction_failure_detail(last_error)) from last_error

    def _persist_snapshot(
        self,
        memory: dict[str, Any],
        older: Sequence[ContextRecord],
        *,
        source_records: Sequence[ContextRecord],
        source_event_count: int,
        trigger: str,
    ) -> ChatContextSnapshot:
        """Atomically advance the replay boundary without mutating prior snapshots."""
        for attempt in range(2):
            try:
                # Serialize all active-snapshot transitions for this session.
                # The singleton slot below is a final database guard, while
                # this row lock keeps source-boundary calculations coherent.
                locked_session = (
                    self.db.query(ChatSession)
                    .filter(ChatSession.id == self.session_id)
                    .with_for_update()
                    .one_or_none()
                )
                if locked_session is None:
                    raise RuntimeError("会话不存在，无法保存上下文压缩检查点")
                self.session = locked_session
                previous_snapshot = (
                    self.db.query(ChatContextSnapshot)
                    .filter(ChatContextSnapshot.session_id == self.session_id, ChatContextSnapshot.is_active.is_(True))
                    .order_by(ChatContextSnapshot.id.desc())
                    .first()
                )
                self.db.query(ChatContextSnapshot).filter(
                    ChatContextSnapshot.session_id == self.session_id,
                    ChatContextSnapshot.is_active.is_(True),
                ).update(
                    {"is_active": False, "active_slot": None, "invalidation_reason": "replaced"},
                    synchronize_session=False,
                )
                covered_message_id = max(
                    [record.message_id or 0 for record in older], default=0
                )
                snapshot = ChatContextSnapshot(
                    session_id=self.session_id,
                    source_start_event_id=(
                        int(previous_snapshot.source_start_event_id or 0)
                        if previous_snapshot is not None
                        else older[0].id
                    ),
                    compacted_through_event_id=older[-1].id,
                    compacted_through_message_id=covered_message_id,
                    retained_from_event_id=older[-1].id + 1,
                    summary_json=json.dumps(memory, ensure_ascii=False),
                    strategy="agentic",
                    trigger=trigger,
                    model_id=self.model.id,
                    input_budget_tokens=self.usable_budget,
                    source_event_count=source_event_count,
                    source_prefix_hash=context_prefix_hash(source_records, source_event_count),
                    context_generation=int(self.session.context_generation or 0) if self.session else 0,
                    is_active=True,
                    active_slot=1,
                )
                self.db.add(snapshot)
                self.db.commit()
                return snapshot
            except SQLAlchemyError:
                self.db.rollback()
                if attempt:
                    raise
        raise RuntimeError("无法保存上下文压缩检查点")  # pragma: no cover - defensive exhaustiveness.

    async def prepare(
        self,
        compaction_model: BaseChatModel | None = None,
        *,
        force_compaction: bool = False,
        rebuild: bool = False,
        trigger: str = "automatic",
    ) -> PreparedAgentContext:
        source_records = self._source_records()
        checkpoint = None if rebuild else self._checkpoint(source_records)
        memory = _fit_memory_to_budget(
            {} if rebuild else (_safe_json(checkpoint.summary_json, {}) if checkpoint else {}),
            self.memory_target_tokens,
        )
        active = self._records_after_checkpoint(source_records, checkpoint)
        prior_source_count = len(source_records) - len(active)
        stats = self._stats(memory, active, "ready", checkpoint)
        raw_input_tokens = stats["used_tokens"]
        if force_compaction or stats["used_tokens"] >= self.trigger_budget:
            older, retained = self._partition_for_compaction(active, memory)
            if older:
                if compaction_model is None:
                    raise ContextBudgetError("当前上下文需要模型压缩，但压缩模型不可用")
                memory = await self._model_memory(compaction_model, memory, older)
                checkpoint = self._persist_snapshot(
                    memory,
                    older,
                    source_records=source_records,
                    source_event_count=prior_source_count + len(older),
                    trigger=trigger,
                )
                active = retained
                stats = self._stats(memory, active, "compacted", checkpoint)
            elif rebuild:
                # A rebuild may legitimately find that the complete ledger is
                # already short enough to replay. Do not leave an old snapshot
                # active, because it was deliberately excluded from this pass.
                self.db.query(ChatContextSnapshot).filter(
                    ChatContextSnapshot.session_id == self.session_id,
                    ChatContextSnapshot.is_active.is_(True),
                ).update(
                    {"is_active": False, "active_slot": None, "invalidation_reason": "manual_rebuild"},
                    synchronize_session=False,
                )
                self.db.commit()

        if stats["used_tokens"] > self.usable_budget:
            raise ContextBudgetError(
                "当前模型的输入预算无法容纳系统规则、工具定义、文档工作区、近期事件与本轮请求；"
                "请使用更大上下文模型或缩短本轮附加内容"
            )
        stats.update(
            {
                "requires_compaction": False,
                "can_fit_after_compaction": True,
                "overflow_tokens": 0,
                "projected_used_tokens": stats["used_tokens"],
                "compiled_input_tokens": stats["used_tokens"],
                "raw_input_tokens": raw_input_tokens,
                "active_context_threshold_tokens": self.trigger_budget,
                "compaction_target_tokens": self.target_budget,
                "compaction_summary_token_budget": self.memory_target_tokens,
            }
        )
        return PreparedAgentContext(
            memory=memory,
            history=[
                record.to_message(
                    self.workspace.revision,
                    self.tool_result_max_tokens,
                    self.db,
                    self.model.provider.provider_type.value if self.model.provider is not None else "openai_compatible",
                    self.model.is_multimodal,
                )
                for record in active
            ],
            workspace_map=self.workspace.map_payload(max(18, int(72 * self.budget_multiplier))),
            stats=stats,
        )
