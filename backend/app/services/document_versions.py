from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_version import DocumentVersion, DocumentVersionSource


def create_document_version(
    db: Session,
    document: Document,
    user_id: int | None,
    source: DocumentVersionSource,
    label: str,
) -> DocumentVersion:
    """将当前文档状态固化为不可变快照；调用方与文档更新使用同一事务。"""
    db.flush()
    last_number = (
        db.query(func.max(DocumentVersion.version_number))
        .filter(DocumentVersion.document_id == document.id)
        .scalar()
    )
    version = DocumentVersion(
        document_id=document.id,
        version_number=(last_number or 0) + 1,
        title=document.title,
        html=document.current_html,
        source=source,
        label=label[:256],
        created_by_id=user_id,
    )
    db.add(version)
    return version
