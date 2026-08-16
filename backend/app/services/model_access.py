from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import false, or_
from sqlalchemy.orm import Query

from app.models.ai_image_model import AIImageModel
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.models.user import User, UserRole
from app.models.user_group import UserGroup


# China Standard Time has no daylight-saving transitions. A fixed offset keeps
# availability checks deterministic on Windows Python installs without tzdata.
_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _time_of_day_minutes(value: object) -> int | None:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return None
    try:
        hour, minute = int(value[:2]), int(value[3:])
    except ValueError:
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour * 60 + minute


def is_available_in_time_ranges(
    availability_time_ranges: object, *, now: datetime | None = None
) -> bool:
    """Return whether a daily China Standard Time schedule permits a call.

    Empty schedules preserve the historical all-day behavior. Intervals include
    ``start`` and exclude ``end``; an end earlier than start spans midnight.
    Invalid persisted JSON fails closed rather than accidentally exposing a
    model outside an administrator-configured schedule.
    """
    if availability_time_ranges in (None, []):
        return True
    if not isinstance(availability_time_ranges, list):
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(_SHANGHAI)
    minute = local.hour * 60 + local.minute
    for item in availability_time_ranges:
        if not isinstance(item, dict):
            return False
        start = _time_of_day_minutes(item.get("start"))
        end = _time_of_day_minutes(item.get("end"))
        if start is None or end is None or start == end:
            return False
        if start < end and start <= minute < end:
            return True
        if start > end and (minute >= start or minute < end):
            return True
    return False


def is_model_available(model: AIModel, *, now: datetime | None = None) -> bool:
    return bool(
        model.is_enabled
        and model.provider is not None
        and model.provider.is_enabled
        and is_available_in_time_ranges(getattr(model.provider, "availability_time_ranges", []), now=now)
        and is_available_in_time_ranges(getattr(model, "availability_time_ranges", []), now=now)
    )


def is_image_model_available(model: AIImageModel, *, now: datetime | None = None) -> bool:
    return bool(
        model.deleted_at is None
        and model.is_enabled
        and model.provider is not None
        and model.provider.is_enabled
        and is_available_in_time_ranges(getattr(model.provider, "availability_time_ranges", []), now=now)
        and is_available_in_time_ranges(getattr(model, "availability_time_ranges", []), now=now)
    )


def can_access_model(user: User, model: AIModel, *, now: datetime | None = None) -> bool:
    """Check both operational availability and the caller's model permission."""
    if not is_model_available(model, now=now):
        return False
    if user.role == UserRole.ADMIN or model.access_mode != "restricted":
        return True
    if any(allowed_user.id == user.id for allowed_user in model.allowed_users):
        return True
    user_group_ids = {group.id for group in user.groups}
    return any(group.id in user_group_ids for group in model.allowed_groups)


def accessible_models_query(query: Query, user: User, *, require_enabled: bool = True) -> Query:
    """Restrict a model query to models usable by ``user``.

    Historical reports use ``require_enabled=False`` so a later operational
    disable never hides calls that the viewer was allowed to inspect.
    """
    if require_enabled:
        query = query.filter(
            AIModel.is_enabled.is_(True),
            AIModel.provider.has(AIProvider.is_enabled.is_(True)),
        )
    if user.role == UserRole.ADMIN:
        return query

    conditions = [
        AIModel.access_mode == "all",
        AIModel.allowed_users.any(User.id == user.id),
    ]
    group_ids = [group.id for group in user.groups]
    if group_ids:
        conditions.append(AIModel.allowed_groups.any(UserGroup.id.in_(group_ids)))
    else:
        conditions.append(false())
    return query.filter(or_(*conditions))


def can_access_image_model(user: User, model: AIImageModel, *, now: datetime | None = None) -> bool:
    if not is_image_model_available(model, now=now):
        return False
    if user.role == UserRole.ADMIN or model.access_mode != "restricted":
        return True
    if any(allowed_user.id == user.id for allowed_user in model.allowed_users):
        return True
    user_group_ids = {group.id for group in user.groups}
    return any(group.id in user_group_ids for group in model.allowed_groups)


def accessible_image_models_query(query: Query, user: User, *, require_enabled: bool = True) -> Query:
    query = query.filter(AIImageModel.deleted_at.is_(None))
    if require_enabled:
        query = query.filter(
            AIImageModel.is_enabled.is_(True),
            AIImageModel.provider.has(AIProvider.is_enabled.is_(True)),
        )
    if user.role == UserRole.ADMIN:
        return query
    conditions = [
        AIImageModel.access_mode == "all",
        AIImageModel.allowed_users.any(User.id == user.id),
    ]
    group_ids = [group.id for group in user.groups]
    if group_ids:
        conditions.append(AIImageModel.allowed_groups.any(UserGroup.id.in_(group_ids)))
    else:
        conditions.append(false())
    return query.filter(or_(*conditions))
