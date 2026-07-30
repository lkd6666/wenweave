from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.ai_provider import ProviderType


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


class ModelRead(BaseModel):
    id: int
    provider_id: int
    model_name: str
    display_name: str
    description: str
    context_window_tokens: int = Field(default=32768, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int = Field(default=24576, ge=1024, le=2_000_000)
    max_output_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    tool_result_max_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    is_default: bool
    is_multimodal: bool = False
    supports_disabled_thinking: bool = True
    access_mode: Literal["all", "restricted"] = "all"
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)
    thinking_config: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class ModelCreate(BaseModel):
    model_name: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=1024)
    context_window_tokens: int = Field(default=32768, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int = Field(default=24576, ge=1024, le=2_000_000)
    max_output_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    tool_result_max_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    is_default: bool = False
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


class ModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    context_window_tokens: int | None = Field(default=None, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int | None = Field(default=None, ge=1024, le=2_000_000)
    max_output_tokens: int | None = Field(default=None, ge=128, le=1_000_000)
    tool_result_max_tokens: int | None = Field(default=None, ge=128, le=1_000_000)
    is_default: bool | None = None
    is_multimodal: bool | None = None
    supports_disabled_thinking: bool | None = None
    thinking_config: dict[str, Any] | None = None
    access_mode: Literal["all", "restricted"] | None = None
    allowed_user_ids: list[int] | None = Field(default=None, max_length=500)
    allowed_group_ids: list[int] | None = Field(default=None, max_length=500)


class ProviderRead(BaseModel):
    id: int
    name: str
    provider_type: ProviderType
    base_url: str
    api_key_masked: str
    models: list[ModelRead] = []


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider_type: ProviderType
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1)


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    api_key: str | None = None  # 留空表示不修改现有密钥


class ModelPresetRead(BaseModel):
    model_name: str
    display_name: str
    description: str = ""
    context_window_tokens: int = 32768
    context_compaction_threshold_tokens: int = 24576
    max_output_tokens: int = 8192
    tool_result_max_tokens: int = 8192
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
    model_names: list[str] = Field(min_length=1, max_length=30)
    # Filled from the immediately preceding discovery response so that
    # provider-reported capacity is retained when a preset is installed.
    model_capabilities: list[ModelPresetRead] = Field(default_factory=list, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    set_as_default: bool = True


class PresetDiscoveryRequest(BaseModel):
    api_key: str = Field(min_length=1)


class ModelBulkCreateItem(BaseModel):
    model_name: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=1024)
    context_window_tokens: int = Field(default=32768, ge=8192, le=2_000_000)
    context_compaction_threshold_tokens: int = Field(default=24576, ge=1024, le=2_000_000)
    max_output_tokens: int = Field(default=8192, ge=128, le=1_000_000)
    tool_result_max_tokens: int = Field(default=8192, ge=128, le=1_000_000)
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
