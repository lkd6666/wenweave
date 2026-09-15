import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.token_budgets import DEFAULT_TOOL_RESULT_MAX_TOKENS
from app.models.ai_provider import ProviderType


ThinkingEffort = Literal["auto", "minimal", "low", "medium", "high", "xhigh", "max"]
ImageProtocol = Literal["", "openai_images", "dashscope_images", "volcengine_ark_images"]
_TIME_OF_DAY_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AvailabilityTimeRange(BaseModel):
    """One daily, minute-precision availability interval in China Standard Time."""

    start: str
    end: str

    @model_validator(mode="after")
    def validate_range(self):
        if not _TIME_OF_DAY_PATTERN.fullmatch(self.start) or not _TIME_OF_DAY_PATTERN.fullmatch(self.end):
            raise ValueError("可用时段必须使用 HH:mm 格式")
        if self.start == self.end:
            raise ValueError("可用时段的开始和结束时间不能相同")
        return self


def _time_of_day_minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _validate_availability_time_ranges(ranges: list[AvailabilityTimeRange]) -> None:
    """Reject overlapping daily ranges while allowing adjoining intervals."""
    segments: list[tuple[int, int]] = []
    for item in ranges:
        start = _time_of_day_minutes(item.start)
        end = _time_of_day_minutes(item.end)
        if start < end:
            segments.append((start, end))
        else:
            segments.append((start, 24 * 60))
            if end:
                segments.append((0, end))
    previous_end = -1
    for start, end in sorted(segments):
        if start < previous_end:
            raise ValueError("可用时段不能重叠或重复")
        previous_end = max(previous_end, end)


class AvailabilityTimeRanges(BaseModel):
    """Shared validator so every managed object accepts the same schedule shape."""

    availability_time_ranges: list[AvailabilityTimeRange] = Field(default_factory=list, max_length=48)

    @model_validator(mode="after")
    def validate_ranges(self):
        _validate_availability_time_ranges(self.availability_time_ranges)
        return self


class AvailabilityTimeRangesUpdate(BaseModel):
    availability_time_ranges: list[AvailabilityTimeRange] | None = Field(default=None, max_length=48)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.availability_time_ranges is not None:
            _validate_availability_time_ranges(self.availability_time_ranges)
        return self


def _validate_token_budget(
    context_window_tokens: int,
    context_compaction_threshold_tokens: int,
    max_output_tokens: int,
    tool_result_max_tokens: int,
) -> None:
    if context_compaction_threshold_tokens + max_output_tokens > context_window_tokens:
        raise ValueError("压缩阈值与最大输出 token 之和不能超过模型最大上下文窗口")
    if tool_result_max_tokens > context_compaction_threshold_tokens:
        raise ValueError("单次工具返回 token 上限不能超过压缩阈值")


class ModelRead(AvailabilityTimeRanges):
    id: int
    provider_id: int
    provider_name: str
    model_name: str
    display_name: str
    description: str
    context_window_tokens: int = Field(default=32768, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int = Field(default=24576, ge=1024, le=2_000_000)
    max_output_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    tool_result_max_tokens: int = Field(default=DEFAULT_TOOL_RESULT_MAX_TOKENS, ge=128, le=1_000_000)
    is_default: bool
    is_enabled: bool = True
    is_multimodal: bool = False
    supports_disabled_thinking: bool = True
    default_thinking_effort: ThinkingEffort = "auto"
    prompt_cache_enabled: bool = False
    access_mode: Literal["all", "restricted"] = "all"
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)
    thinking_config: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class ModelCreate(AvailabilityTimeRanges):
    model_name: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=1024)
    context_window_tokens: int = Field(default=32768, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int = Field(default=24576, ge=1024, le=2_000_000)
    max_output_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    tool_result_max_tokens: int = Field(default=DEFAULT_TOOL_RESULT_MAX_TOKENS, ge=128, le=1_000_000)
    is_default: bool = False
    is_enabled: bool = True
    is_multimodal: bool = False
    supports_disabled_thinking: bool = True
    default_thinking_effort: ThinkingEffort = "auto"
    prompt_cache_enabled: bool = False
    thinking_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_budget(self):
        _validate_token_budget(
            self.context_window_tokens,
            self.context_compaction_threshold_tokens,
            self.max_output_tokens,
            self.tool_result_max_tokens,
        )
        return self


class ModelUpdate(AvailabilityTimeRangesUpdate):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    context_window_tokens: int | None = Field(default=None, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int | None = Field(default=None, ge=1024, le=2_000_000)
    max_output_tokens: int | None = Field(default=None, ge=128, le=1_000_000)
    tool_result_max_tokens: int | None = Field(default=None, ge=128, le=1_000_000)
    is_default: bool | None = None
    is_enabled: bool | None = None
    is_multimodal: bool | None = None
    supports_disabled_thinking: bool | None = None
    default_thinking_effort: ThinkingEffort | None = None
    prompt_cache_enabled: bool | None = None
    thinking_config: dict[str, Any] | None = None
    access_mode: Literal["all", "restricted"] | None = None
    allowed_user_ids: list[int] | None = Field(default=None, max_length=500)
    allowed_group_ids: list[int] | None = Field(default=None, max_length=500)


class ImageModelRead(AvailabilityTimeRanges):
    id: int
    provider_id: int
    model_name: str
    display_name: str
    description: str
    supported_aspect_ratios: list[str] = Field(default_factory=list)
    supported_qualities: list[str] = Field(default_factory=list)
    is_default: bool
    is_enabled: bool = True
    access_mode: Literal["all", "restricted"] = "all"
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)
    operations: list[Literal["generate", "edit"]] = Field(default_factory=lambda: ["generate"])
    adapter_config: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class ImageModelCreate(AvailabilityTimeRanges):
    model_name: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=1024)
    supported_aspect_ratios: list[Literal["square", "portrait", "landscape"]] = Field(default_factory=list)
    supported_qualities: list[str] = Field(default_factory=list, max_length=12)
    is_default: bool = False
    is_enabled: bool = True
    access_mode: Literal["all", "restricted"] = "all"
    allowed_user_ids: list[int] | None = Field(default=None, max_length=500)
    allowed_group_ids: list[int] | None = Field(default=None, max_length=500)
    adapter_config: dict[str, Any] = Field(default_factory=dict)


class ImageModelUpdate(AvailabilityTimeRangesUpdate):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    supported_aspect_ratios: list[Literal["square", "portrait", "landscape"]] | None = None
    supported_qualities: list[str] | None = Field(default=None, max_length=12)
    is_default: bool | None = None
    is_enabled: bool | None = None
    access_mode: Literal["all", "restricted"] | None = None
    allowed_user_ids: list[int] | None = Field(default=None, max_length=500)
    allowed_group_ids: list[int] | None = Field(default=None, max_length=500)
    adapter_config: dict[str, Any] | None = None


class ProviderRead(AvailabilityTimeRanges):
    id: int
    name: str
    provider_type: ProviderType
    base_url: str
    image_protocol: ImageProtocol = ""
    image_base_url: str = ""
    is_enabled: bool = True
    api_key_masked: str
    models: list[ModelRead] = []
    image_models: list[ImageModelRead] = []


class ProviderCreate(AvailabilityTimeRanges):
    name: str = Field(min_length=1, max_length=128)
    provider_type: ProviderType
    base_url: str = Field(min_length=1, max_length=512)
    image_protocol: ImageProtocol = ""
    image_base_url: str = Field(default="", max_length=512)
    is_enabled: bool = True
    api_key: str = Field(min_length=1)


class ProviderUpdate(AvailabilityTimeRangesUpdate):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider_type: ProviderType | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    image_protocol: ImageProtocol | None = None
    image_base_url: str | None = Field(default=None, max_length=512)
    is_enabled: bool | None = None
    api_key: str | None = None  # 留空表示不修改现有密钥


class ModelPresetRead(BaseModel):
    model_name: str
    display_name: str
    description: str = ""
    context_window_tokens: int = 32768
    context_compaction_threshold_tokens: int = 24576
    max_output_tokens: int = 8192
    tool_result_max_tokens: int = DEFAULT_TOOL_RESULT_MAX_TOKENS
    is_multimodal: bool = False
    supports_disabled_thinking: bool = True
    thinking_config: dict[str, Any] = Field(default_factory=dict)
    thinking_efforts: list[str] = Field(default_factory=list)


class ProviderPresetRead(BaseModel):
    id: str
    name: str
    provider_type: ProviderType
    base_url: str
    api_key_hint: str = ""
    models: list[ModelPresetRead] = Field(default_factory=list)


class PresetInstallRequest(BaseModel):
    api_key: str = Field(min_length=1)
    provider_type: ProviderType | None = None
    model_names: list[str] = Field(min_length=1, max_length=30)
    # Filled from the immediately preceding discovery response so that
    # provider-reported capacity is retained when a preset is installed.
    model_capabilities: list[ModelPresetRead] = Field(default_factory=list, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    set_as_default: bool = True


class PresetDiscoveryRequest(BaseModel):
    api_key: str = Field(min_length=1)
    provider_type: ProviderType | None = None


class ModelBulkCreateItem(AvailabilityTimeRanges):
    model_name: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=1024)
    context_window_tokens: int = Field(default=32768, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int = Field(default=24576, ge=1024, le=2_000_000)
    max_output_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    tool_result_max_tokens: int = Field(default=DEFAULT_TOOL_RESULT_MAX_TOKENS, ge=128, le=1_000_000)
    is_enabled: bool = True
    is_multimodal: bool = False
    supports_disabled_thinking: bool = True
    thinking_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_budget(self):
        _validate_token_budget(
            self.context_window_tokens,
            self.context_compaction_threshold_tokens,
            self.max_output_tokens,
            self.tool_result_max_tokens,
        )
        return self


class ModelBulkCreateRequest(BaseModel):
    models: list[ModelBulkCreateItem] = Field(min_length=1, max_length=100)


class ModelBulkCreateResult(BaseModel):
    created: list[ModelRead] = Field(default_factory=list)
    skipped_model_names: list[str] = Field(default_factory=list)


class ModelDiscoveryItem(ModelPresetRead):
    source: str
    context_window_source: str = "保守默认值"


class ModelDiscoveryResult(BaseModel):
    models: list[ModelDiscoveryItem] = Field(default_factory=list)
    source: str
    warning: str | None = None


class TestConnectionRequest(BaseModel):
    model_name: str = Field(min_length=1, max_length=256)


class TestConnectionResult(BaseModel):
    success: bool
    message: str
    latency_ms: int | None = None
