from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ID_TYPE
from app.models.user_group import model_group_access, model_user_access

DEFAULT_CONTEXT_WINDOW_TOKENS = 32_768
DEFAULT_CONTEXT_COMPACTION_THRESHOLD_TOKENS = 24_576
DEFAULT_MAX_OUTPUT_TOKENS = 8_192
DEFAULT_TOOL_RESULT_MAX_TOKENS = 4_096


class AIModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    # Used by the Agent context budgeter.  Providers do not consistently expose
    # this through /models, so administrators may override the conservative
    # default for custom models.
    # ``context_window_tokens`` is the provider-advertised total request limit.
    # The other three values are per-model operational budgets used by the
    # Agent, never process-wide settings.  Their invariant is checked by the
    # provider-management API before a model can be saved.
    context_window_tokens: Mapped[int] = mapped_column(
        nullable=False,
        default=DEFAULT_CONTEXT_WINDOW_TOKENS,
        server_default=str(DEFAULT_CONTEXT_WINDOW_TOKENS),
    )
    context_compaction_threshold_tokens: Mapped[int] = mapped_column(
        nullable=False,
        default=DEFAULT_CONTEXT_COMPACTION_THRESHOLD_TOKENS,
        server_default=str(DEFAULT_CONTEXT_COMPACTION_THRESHOLD_TOKENS),
    )
    max_output_tokens: Mapped[int] = mapped_column(
        nullable=False,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        server_default=str(DEFAULT_MAX_OUTPUT_TOKENS),
    )
    tool_result_max_tokens: Mapped[int] = mapped_column(
        nullable=False,
        default=DEFAULT_TOOL_RESULT_MAX_TOKENS,
        server_default=str(DEFAULT_TOOL_RESULT_MAX_TOKENS),
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ``all`` 保持历史行为；``restricted`` 时仅直接授权的用户或所属获授权组可使用。
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="all", server_default="all")
    # Provider-specific reasoning request mappings. Besides enabled/disabled, presets
    # may carry an ``efforts`` map such as {"low": {"reasoning_effort": "low"}}.
    thinking_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider: Mapped["AIProvider"] = relationship("AIProvider", back_populates="models")
    allowed_users = relationship("User", secondary=model_user_access, back_populates="allowed_models")
    allowed_groups = relationship("UserGroup", secondary=model_group_access, back_populates="allowed_models")

    @property
    def allowed_user_ids(self) -> list[int]:
        return [user.id for user in self.allowed_users]

    @property
    def allowed_group_ids(self) -> list[int]:
        return [group.id for group in self.allowed_groups]
