from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select, union_all
from sqlalchemy.orm import Query as SqlQuery
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.ai_model import AIModel
from app.models.document import Document
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.model_call_record import ModelCallRecord
from app.models.user import User
from app.schemas.workboard import (
    WorkboardModelRank,
    WorkboardOverview,
    WorkboardPeriod,
    WorkboardRead,
    WorkboardTokenStats,
    WorkboardTweetActivity,
    WorkboardUserRank,
)
from app.services.model_access import accessible_models_query


router = APIRouter(prefix="/api/workboard", tags=["workboard"])
# Shanghai has no daylight-saving transitions. A fixed UTC+08:00 object keeps
# period boundaries deterministic even in minimal Windows Python runtimes that
# do not bundle the optional IANA ``tzdata`` package.
_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
_RANK_LIMIT = 10


def _period_range(period: WorkboardPeriod, now: datetime | None = None) -> tuple[datetime, datetime]:
    current = (now or datetime.now(timezone.utc)).astimezone(_SHANGHAI)
    if period == "today":
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7d":
        start = current - timedelta(days=7)
    elif period == "month":
        start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = current - timedelta(days=30)
    return start.astimezone(timezone.utc), current.astimezone(timezone.utc)


def _int(value: object) -> int:
    return int(value or 0)


def _token_values(row: object, *, prefix: str = "") -> WorkboardTokenStats:
    def value(name: str) -> int:
        return _int(getattr(row, f"{prefix}{name}"))

    input_tokens = value("input_tokens")
    cache_read_tokens = value("cache_read_tokens")
    return WorkboardTokenStats(
        input_tokens=input_tokens,
        output_tokens=value("output_tokens"),
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=value("cache_write_tokens"),
        cache_hit_rate=round(cache_read_tokens * 100 / input_tokens, 2) if input_tokens else None,
        usage_unreported_calls=value("usage_unreported_calls"),
    )


def _visible_calls(db: Session, current_user: User, start_at: datetime, end_at: datetime) -> SqlQuery:
    query = db.query(ModelCallRecord).join(AIModel, AIModel.id == ModelCallRecord.model_id)
    return accessible_models_query(query, current_user).filter(
        ModelCallRecord.started_at >= start_at,
        ModelCallRecord.started_at < end_at,
    )


def _aggregate_columns() -> tuple[object, ...]:
    return (
        func.count(ModelCallRecord.id).label("call_count"),
        func.coalesce(func.sum(ModelCallRecord.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(ModelCallRecord.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(ModelCallRecord.cache_read_tokens), 0).label("cache_read_tokens"),
        func.coalesce(func.sum(ModelCallRecord.cache_write_tokens), 0).label("cache_write_tokens"),
        func.coalesce(
            func.sum(case((ModelCallRecord.usage_reported.is_(False), 1), else_=0)), 0
        ).label("usage_unreported_calls"),
    )


@router.get("", response_model=WorkboardRead)
def get_workboard(
    period: WorkboardPeriod = Query("30d"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkboardRead:
    start_at, end_at = _period_range(period)
    aggregate = _visible_calls(db, current_user, start_at, end_at).with_entities(*_aggregate_columns()).one()
    overview_tokens = _token_values(aggregate)
    visible_calls = _visible_calls(db, current_user, start_at, end_at)

    model_rows = (
        visible_calls.with_entities(
            AIModel.id.label("model_id"),
            AIModel.display_name.label("display_name"),
            *_aggregate_columns(),
        )
        .group_by(AIModel.id, AIModel.display_name)
        .order_by(func.count(ModelCallRecord.id).desc(), AIModel.display_name.asc(), AIModel.id.asc())
        .limit(_RANK_LIMIT)
        .all()
    )
    model_ranking = [
        WorkboardModelRank(
            model_id=row.model_id,
            display_name=row.display_name,
            call_count=_int(row.call_count),
            **_token_values(row).model_dump(),
        )
        for row in model_rows
    ]

    user_rows = (
        visible_calls.outerjoin(User, User.id == ModelCallRecord.user_id)
        .with_entities(
            ModelCallRecord.user_id.label("user_id"),
            User.display_name.label("display_name"),
            User.username.label("username"),
            *_aggregate_columns(),
        )
        .group_by(ModelCallRecord.user_id, User.display_name, User.username)
        .order_by(func.count(ModelCallRecord.id).desc(), User.display_name.asc(), User.username.asc())
        .limit(_RANK_LIMIT)
        .all()
    )
    user_ranking = [
        WorkboardUserRank(
            user_id=row.user_id,
            display_name=(row.display_name or row.username or "已删除用户"),
            username=row.username or "",
            call_count=_int(row.call_count),
            **_token_values(row).model_dump(),
        )
        for row in user_rows
    ]

    created_documents = _int(
        db.query(func.count(Document.id))
        .filter(Document.created_at >= start_at, Document.created_at < end_at)
        .scalar()
    )
    ai_versions = _int(
        db.query(func.count(DocumentVersion.id))
        .filter(
            DocumentVersion.created_at >= start_at,
            DocumentVersion.created_at < end_at,
            DocumentVersion.source == DocumentVersionSource.AI,
        )
        .scalar()
    )
    manual_versions = _int(
        db.query(func.count(DocumentVersion.id))
        .filter(
            DocumentVersion.created_at >= start_at,
            DocumentVersion.created_at < end_at,
            DocumentVersion.source.in_([DocumentVersionSource.MANUAL, DocumentVersionSource.RESTORE]),
        )
        .scalar()
    )
    creator_ids = union_all(
        select(Document.created_by_id.label("user_id")).where(
            Document.created_at >= start_at,
            Document.created_at < end_at,
            Document.created_by_id.is_not(None),
        ),
        select(DocumentVersion.created_by_id.label("user_id")).where(
            DocumentVersion.created_at >= start_at,
            DocumentVersion.created_at < end_at,
            DocumentVersion.created_by_id.is_not(None),
        ),
    ).subquery()
    tweet_activity = WorkboardTweetActivity(
        total_documents=_int(db.query(func.count(Document.id)).scalar()),
        created_documents=created_documents,
        active_creators=_int(db.query(func.count(func.distinct(creator_ids.c.user_id))).scalar()),
        ai_versions=ai_versions,
        manual_versions=manual_versions,
    )
    return WorkboardRead(
        period=period,
        start_at=start_at,
        end_at=end_at,
        overview=WorkboardOverview(
            model_call_count=_int(aggregate.call_count),
            active_users=_int(
                _visible_calls(db, current_user, start_at, end_at)
                .with_entities(func.count(func.distinct(ModelCallRecord.user_id)))
                .scalar()
            ),
            **overview_tokens.model_dump(),
        ),
        model_ranking=model_ranking,
        user_ranking=user_ranking,
        tweet_activity=tweet_activity,
    )
