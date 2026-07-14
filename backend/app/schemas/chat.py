from datetime import datetime

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.agent_run import AgentRunStatus
from app.models.chat_message import MessageRole
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
    status: Literal["running", "success", "error"]
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
    tokens_saved: int = 0
    context_policy: str = ""
    max_output_tokens: int = 0
    tool_result_max_tokens: int = 0
    active_context_threshold_tokens: int = 0
    budget_multiplier: float = 1.0
    requires_compaction: bool = False
    can_fit_after_compaction: bool = True
    overflow_tokens: int = 0
    projected_used_tokens: int = 0


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


class SelectedElementInput(BaseModel):
    """浏览器预览中用户明确选中的元素源码，仅作为本轮 Agent 的定位上下文。"""

    selector: str = Field(min_length=1, max_length=1024)
    tag_name: str = Field(min_length=1, max_length=64)
    html: str = Field(min_length=1, max_length=MAX_SELECTED_ELEMENT_HTML_CHARS)
    text: str = Field(default="", max_length=MAX_SELECTED_ELEMENT_TEXT_CHARS)

    @model_validator(mode="before")
    @classmethod
    def strip_inline_data(cls, value):
        if not isinstance(value, dict):
            return value
        return normalize_selected_element(value)


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: MessageRole
    content: str
    tool_calls: list[ToolExecutionRead] = Field(default_factory=list)
    reasoning_trace: ReasoningTraceRead = Field(default_factory=ReasoningTraceRead)
    turn_blocks: list[AssistantTurnBlockRead] = Field(default_factory=list)
    selected_elements: list[SelectedElementInput] = Field(default_factory=list)
    can_revert: bool = False
    created_at: datetime


class ChatSendRequest(BaseModel):
    message: str
    model_id: int
    client_request_id: str = Field(min_length=8, max_length=96)
    thinking_mode: Literal["auto", "enabled", "disabled"] = "auto"
    thinking_effort: Literal["auto", "minimal", "low", "medium", "high", "xhigh", "max"] = "auto"
    selected_elements: list[SelectedElementInput] = Field(default_factory=list, max_length=12)
    layout_reference_id: str | None = Field(default=None, min_length=36, max_length=36)

    @model_validator(mode="after")
    def limit_selected_context(self):
        self.selected_elements = [
            SelectedElementInput.model_validate(item)
            for item in normalize_selected_elements([item.model_dump() for item in self.selected_elements])
        ]
        return self


class ChatRevertRequest(BaseModel):
    message_id: int = Field(gt=0)


class AgentRunRead(BaseModel):
    run_id: str
    status: AgentRunStatus
    user_message_id: int
    assistant_message_id: int | None = None
    error_message: str = ""
