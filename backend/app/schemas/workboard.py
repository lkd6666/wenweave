from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


WorkboardPeriod = Literal["today", "7d", "30d", "month"]


class WorkboardTokenStats(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cache_hit_rate: float | None = None
    usage_unreported_calls: int = 0


class WorkboardModelRank(WorkboardTokenStats):
    model_id: int
    display_name: str
    call_count: int = 0


class WorkboardUserRank(WorkboardTokenStats):
    user_id: int | None = None
    display_name: str
    username: str = ""
    call_count: int = 0


class WorkboardTweetActivity(BaseModel):
    total_documents: int = 0
    created_documents: int = 0
    active_creators: int = 0
    ai_versions: int = 0
    manual_versions: int = 0


class WorkboardOverview(WorkboardTokenStats):
    model_call_count: int = 0
    active_users: int = 0


class WorkboardRead(BaseModel):
    period: WorkboardPeriod
    start_at: datetime
    end_at: datetime
    overview: WorkboardOverview
    model_ranking: list[WorkboardModelRank] = Field(default_factory=list)
    user_ranking: list[WorkboardUserRank] = Field(default_factory=list)
    tweet_activity: WorkboardTweetActivity
