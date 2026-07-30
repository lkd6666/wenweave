from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.operation_log import OperationLog, OperationLogStatus
from app.schemas.operation_log import OperationLogListRead, OperationLogRead


router = APIRouter(prefix="/api/operation-logs", tags=["operation-logs"])


def _to_read(item: OperationLog) -> OperationLogRead:
    try:
        details = json.loads(item.details_json or "{}")
    except json.JSONDecodeError:
        details = {}
    return OperationLogRead(
        id=item.id,
        actor_user_id=item.actor_user_id,
        actor_username=item.actor_username,
        actor_display_name=item.actor_display_name,
        action=item.action,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        resource_name=item.resource_name,
        document_id=item.document_id,
        session_id=item.session_id,
        status=item.status,
        summary=item.summary,
        error_summary=item.error_summary,
        details=details if isinstance(details, dict) else {},
        request_id=item.request_id,
        client_ip=item.client_ip,
        user_agent=item.user_agent,
        created_at=item.created_at,
    )


@router.get("", response_model=OperationLogListRead, dependencies=[Depends(require_admin)])
def list_operation_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    actor_user_id: int | None = Query(default=None),
    action: str | None = Query(default=None, max_length=128),
    resource_type: str | None = Query(default=None, max_length=64),
    document_id: int | None = Query(default=None),
    status: OperationLogStatus | None = Query(default=None),
    client_ip: str | None = Query(default=None, max_length=45),
    started_at: datetime | None = Query(default=None),
    ended_at: datetime | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
) -> OperationLogListRead:
    query = db.query(OperationLog)
    if actor_user_id is not None:
        query = query.filter(OperationLog.actor_user_id == actor_user_id)
    if action:
        query = query.filter(OperationLog.action == action.strip())
    if resource_type:
        query = query.filter(OperationLog.resource_type == resource_type.strip())
    if document_id is not None:
        query = query.filter(OperationLog.document_id == document_id)
    if status is not None:
        query = query.filter(OperationLog.status == status)
    if client_ip and client_ip.strip():
        query = query.filter(OperationLog.client_ip == client_ip.strip())
    if started_at is not None:
        query = query.filter(OperationLog.created_at >= started_at)
    if ended_at is not None:
        query = query.filter(OperationLog.created_at <= ended_at)
    if keyword and keyword.strip():
        escaped = keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(
            or_(
                OperationLog.actor_username.ilike(pattern, escape="\\"),
                OperationLog.actor_display_name.ilike(pattern, escape="\\"),
                OperationLog.resource_name.ilike(pattern, escape="\\"),
                OperationLog.summary.ilike(pattern, escape="\\"),
            )
        )
    total = query.count()
    items = (
        query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return OperationLogListRead(items=[_to_read(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/{log_id}", response_model=OperationLogRead, dependencies=[Depends(require_admin)])
def get_operation_log(log_id: int, db: Session = Depends(get_db)) -> OperationLogRead:
    item = db.get(OperationLog, log_id)
    if not item:
        raise HTTPException(status_code=404, detail="操作日志不存在")
    return _to_read(item)
