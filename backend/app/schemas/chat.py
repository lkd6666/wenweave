from datetime import datetime

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings
from app.models.agent_run import AgentRunStatus
from app.models.chat_message import MessageRole
from app.schemas.document import UserReference
from app.schemas.chat_images import ChatImageAttachmentRead
from app.services.selected_elements import (
    MAX_SELECTED_ELEMENT_HTML_CHARS,
    MAX_SELECTED_ELEMENT_TEXT_CHARS,
    normalize_selected_element,
    normalize_selected_elements,
)


class ToolExecutionRead(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # A retry can preserve an unexecuted tool preview as a terminal timeline
    # entry so the user can see what was abandoned without treating it as a
    # failed execution.
    status: Literal["running", "waiting", "success", "error", "interrupted"]
    preparing: bool = False
    result: str | None = None
    html_changed: bool = False
    activity: dict[str, Any] | None = None
    read_range: "ReadRangeRead | None" = None
    change_summary: "ChangeSummaryRead | None" = None


class ReadRangeRead(BaseModel):
    scope: Literal["whole", "range"]
    start_line: int
    end_line: int
    total_lines: int


class ChangeSummaryRead(BaseModel):
    added_lines: int
    removed_lines: int
    changed_lines: int
    diff_preview: str
    diff_truncated: bool = False


class ChatContextStatsRead(BaseModel):
    used_tokens: int = 0
    max_tokens: int = 32768
    usable_tokens: int = 0
    usage_percent: int = 0
    is_estimate: bool = True
    state: str = "ready"
    breakdown: dict[str, int] = Field(default_factory=dict)
    tool_calls_count: int = 0
    tool_summary_replayed_count: int = 0
    tool_compact_replayed_count: int = 0
    tool_full_replayed_count: int = 0
    event_count: int = 0
    replayed_event_count: int = 0
    compaction_strategy: str = ""
    compaction_target_tokens: int = 0
    tokens_saved: int = 0
    context_policy: str = ""
    max_output_tokens: int = 0
    tool_result_max_tokens: int = 0
    effective_tool_preview_tokens: int = 0
    stored_tool_output_count: int = 0
    stored_tool_output_bytes: int = 0
    stored_tool_output_tokens: int = 0
    tool_output_retention_days: int = 0
    active_context_threshold_tokens: int = 0
    budget_multiplier: float = 1.0
    requires_compaction: bool = False
    can_fit_after_compaction: bool = True
    overflow_tokens: int = 0
    projected_used_tokens: int = 0
    conversation_tokens: int = 0
    conversation_message_count: int = 0
    compacted_history_tokens: int = 0
    compacted_history_message_count: int = 0
    runtime_context_state: str = ""
    runtime_input_tokens: int = 0
    runtime_original_tokens: int = 0
    runtime_digested_cycles: int = 0
    runtime_dropped_cycles: int = 0
    runtime_projected_tokens: int = 0
    runtime_visible_output_tokens: int = 0
    runtime_reasoning_tokens: int = 0
    runtime_tool_argument_tokens: int = 0
    run_summarized_cycles: int = 0
    runtime_summary_tokens: int = 0
    input_budget_tokens: int = 0
    last_model_output_tokens: int = 0
    last_model_cached_input_tokens: int = 0
    # The raw ledger and the compiled provider request intentionally use
    # different accounting. The latter is the value shown as the primary UI
    # meter because it is what the next model call will actually receive.
    ledger_tokens: int = 0
    raw_input_tokens: int = 0
    compiled_input_tokens: int = 0
    raw_breakdown: dict[str, int] = Field(default_factory=dict)
    snapshot_id: int = 0
    snapshot_covered_event_count: int = 0
    hot_event_count: int = 0
    cold_event_count: int = 0
    tool_output_retention_mode: str = "session"
    snapshot_source_event_count: int = 0
    snapshot_prefix_valid: bool = False
    archived_branch_count: int = 0
    compaction_location: str = ""
    thinking_capability_fallback: dict[str, Any] | None = None


class ReasoningTraceRead(BaseModel):
    status: Literal["idle", "thinking", "complete", "unavailable"] = "idle"
    content: str = ""
    detail: str = ""


class AssistantTurnBlockRead(BaseModel):
    id: str
    type: Literal["thought", "tool", "content"]
    state: Literal["active", "done"] = "done"
    content: str = ""
    duration_ms: int | None = None
    tool: ToolExecutionRead | None = None


class SelectedElementFingerprint(BaseModel):
    tag_name: str = Field(default="", max_length=64)
    stable_attributes: dict[str, str] = Field(default_factory=dict, max_length=16)
    text: str = Field(default="", max_length=MAX_SELECTED_ELEMENT_TEXT_CHARS)


class SelectedElementLocator(BaseModel):
    path: str = Field(default="", max_length=1024)
    parent_path: str = Field(default="", max_length=1024)
    sibling_index: int = Field(default=0, ge=0, le=10_000)
    fingerprint: SelectedElementFingerprint = Field(default_factory=SelectedElementFingerprint)


class SelectedElementInput(BaseModel):
    """浏览器预览中用户明确选中的元素源码，仅作为本轮 Agent 的定位上下文。"""

    selector: str = Field(min_length=1, max_length=1024)
    tag_name: str = Field(min_length=1, max_length=64)
    html: str = Field(min_length=1, max_length=MAX_SELECTED_ELEMENT_HTML_CHARS)
    text: str = Field(default="", max_length=MAX_SELECTED_ELEMENT_TEXT_CHARS)
    locator: SelectedElementLocator | None = None

    @model_validator(mode="before")
    @classmethod
    def strip_inline_data(cls, value):
        if not isinstance(value, dict):
            return value
        return normalize_selected_element(value)


class ChatMessageModelUsageRead(BaseModel):
    model_names: list[str] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cache_hit_rate: int = 0
    call_count: int = 0
    usage_reported: bool = False


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: MessageRole
    content: str
    created_by: UserReference | None = None
    model_usage: ChatMessageModelUsageRead | None = None
    image_attachments: list["ChatImageAttachmentRead"] = Field(default_factory=list)
    tool_calls: list[ToolExecutionRead] = Field(default_factory=list)
    reasoning_trace: ReasoningTraceRead = Field(default_factory=ReasoningTraceRead)
    turn_blocks: list[AssistantTurnBlockRead] = Field(default_factory=list)
    selected_elements: list[SelectedElementInput] = Field(default_factory=list)
    template_refs: list[dict[str, Any]] = Field(default_factory=list)
    can_revert: bool = False
    created_at: datetime


class ChatHistoryArchiveRead(BaseModel):
    id: int
    source_message_id: int
    reason: str
    message_count: int = 0
    created_at: datetime


class ChatReaskActivationRead(BaseModel):
    archive_id: int
    source_message_id: int
    current_html: str


class ChatSessionLayoutReferenceRead(BaseModel):
    title: str
    site_name: str
    extracted_from: str
    block_count: int
    image_assets: int
    imitation_strength: Literal["style", "structure", "maximum"] = "structure"


class ChatSessionTemplateAttachmentRead(BaseModel):
    id: int
    name: str
    category_id: int | None = None
    source_type: Literal["rich_paste", "source", "ai"]
    html: str
    image_warnings: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChatSessionThemeContextRead(BaseModel):
    proposal_id: str
    theme_key: str
    theme_name: str
    apply_mode: Literal["full", "restrained", "key_components"]
    status: str


class ChatSessionRead(BaseModel):
    id: int
    title: str
    is_archived: bool
    context_start_message_id: int = 0
    visible_message_count: int = 0
    hidden_message_count: int = 0
    layout_reference: ChatSessionLayoutReferenceRead | None = None
    attached_templates: list[ChatSessionTemplateAttachmentRead] = Field(default_factory=list)
    theme_context: ChatSessionThemeContextRead | None = None
    image_model_id: int | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=160)


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ChatSessionImageSettingsUpdate(BaseModel):
    image_model_id: int | None = Field(default=None, gt=0)


class ChatSessionTemplateAttachmentsUpdate(BaseModel):
    template_ids: list[int] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def normalise_template_ids(self):
        self.template_ids = list(dict.fromkeys(item for item in self.template_ids if item > 0))
        return self


class ChatSendRequest(BaseModel):
    message: str = Field(max_length=get_settings().MAX_CHAT_MESSAGE_CHARS)
    model_id: int
    session_id: int = Field(gt=0)
    client_request_id: str = Field(min_length=8, max_length=96)
    thinking_mode: Literal["auto", "enabled", "disabled"] = "auto"
    thinking_effort: Literal["auto", "minimal", "low", "medium", "high", "xhigh", "max"] = "auto"
    selected_elements: list[SelectedElementInput] = Field(default_factory=list, max_length=12)
    # ``None`` means an older caller did not send this field; an explicit list
    # is the requested persistent session selection/order.
    template_ids: list[int] | None = Field(default=None, max_length=6)
    image_attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    layout_reference_id: str | None = Field(default=None, min_length=36, max_length=36)
    layout_reference_assets_confirmed: bool = False
    layout_reference_selected_asset_ids: list[str] = Field(default_factory=list, max_length=50)
    layout_reference_imitation_strength: Literal["style", "structure", "maximum"] = "structure"
    gzh_theme_proposal_id: str | None = Field(default=None, min_length=16, max_length=36)
    reask_from_message_id: int | None = Field(default=None, gt=0)
    reask_conflict_resolution: Literal["discard_current_changes"] | None = None
    reask_conflict_checksum: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def limit_selected_context(self):
        self.selected_elements = [
            SelectedElementInput.model_validate(item)
            for item in normalize_selected_elements([item.model_dump() for item in self.selected_elements])
        ]
        if self.template_ids is not None:
            self.template_ids = list(dict.fromkeys(item for item in self.template_ids if item > 0))
        if self.reask_conflict_resolution and not self.reask_conflict_checksum:
            raise ValueError("确认舍弃修改时缺少文档校验值")
        if self.reask_conflict_checksum and not self.reask_conflict_resolution:
            raise ValueError("文档校验值仅用于确认舍弃修改")
        return self


class ChatContextPreviewRequest(BaseModel):
    """浏览器编辑输入中的临时上下文，仅用于实时预算预估。"""

    model_id: int
    session_id: int = Field(gt=0)
    message: str = Field(default="", max_length=get_settings().MAX_CHAT_MESSAGE_CHARS)
    selected_elements: list[SelectedElementInput] = Field(default_factory=list, max_length=12)
    template_ids: list[int] | None = Field(default=None, max_length=6)
    image_attachment_ids: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def limit_selected_context(self):
        self.selected_elements = [
            SelectedElementInput.model_validate(item)
            for item in normalize_selected_elements([item.model_dump() for item in self.selected_elements])
        ]
        if self.template_ids is not None:
            self.template_ids = list(dict.fromkeys(item for item in self.template_ids if item > 0))
        return self


class ChatContextCompactRequest(BaseModel):
    """Persist a model-generated snapshot for the active session ledger."""

    model_id: int
    session_id: int = Field(gt=0)
    rebuild: bool = False


class ChatRevertRequest(BaseModel):
    message_id: int = Field(gt=0)


class ChatUserQuestionOptionRead(BaseModel):
    id: str
    label: str
    description: str = ""
    style_html: str | None = None


class ChatUserQuestionRead(BaseModel):
    id: str
    run_id: str
    question: str
    options: list[ChatUserQuestionOptionRead] = Field(default_factory=list)
    allow_multiple: bool = False
    include_style: bool = False
    timeout_at: datetime | None = None
    inactivity_seconds: int = Field(default=120, ge=1)
    # The assistant message is not committed until the resumed run finishes.
    # Persisted timeline data keeps that in-flight turn visible after refresh.
    timeline: dict[str, Any] = Field(default_factory=dict)
    event_sequence: int | None = None


class ChatUserQuestionActivityRead(BaseModel):
    timeout_at: datetime | None = None
    inactivity_seconds: int = Field(default=120, ge=1)


class ChatUserQuestionAnswerRequest(BaseModel):
    action: Literal["select", "custom", "skip", "timeout"]
    option_ids: list[str] = Field(default_factory=list, max_length=8)
    custom_requirement: str = Field(default="", max_length=1200)
    client_request_id: str = Field(min_length=8, max_length=96)

    @model_validator(mode="after")
    def validate_answer_shape(self):
        self.option_ids = list(dict.fromkeys(item.strip() for item in self.option_ids if item.strip()))
        self.custom_requirement = self.custom_requirement.strip()
        if self.action == "select" and (not self.option_ids or self.custom_requirement):
            raise ValueError("选择选项时必须提供选项，且不能同时填写新要求")
        if self.action == "custom" and (not self.custom_requirement or self.option_ids):
            raise ValueError("提出新要求时不能同时选择选项")
        if self.action in {"skip", "timeout"} and (self.option_ids or self.custom_requirement):
            raise ValueError("跳过提问时不能提交选项或新要求")
        return self


class AgentRunRead(BaseModel):
    run_id: str
    session_id: int
    status: AgentRunStatus
    user_message_id: int
    assistant_message_id: int | None = None
    error_message: str = ""
    reask_activation: ChatReaskActivationRead | None = None
    user_question: ChatUserQuestionRead | None = None
