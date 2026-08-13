from sqlalchemy import Connection, func, select, update

from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.document_version import DocumentVersion, DocumentVersionSource


def touch_document(document: Document, user_id: int) -> None:
    document.last_modified_by_id = user_id
    # MySQL DATETIME drops tzinfo. Use the same database clock as the column's
    # server default so an AI/manual update cannot be displayed eight hours early.
    document.updated_at = func.now()


def touch_group(group: DocumentGroup, user_id: int) -> None:
    group.last_modified_by_id = user_id
    group.updated_at = func.now()


def repair_document_activity_timestamps(connection: Connection) -> int:
    """Repair legacy UTC writes using the matching database-clock version time."""
    latest_edit_at = (
        select(func.max(DocumentVersion.created_at))
        .where(
            DocumentVersion.document_id == Document.id,
            DocumentVersion.source.in_(
                (
                    DocumentVersionSource.MANUAL,
                    DocumentVersionSource.AI,
                    DocumentVersionSource.RESTORE,
                )
            ),
        )
        .correlate(Document)
        .scalar_subquery()
    )
    result = connection.execute(
        update(Document)
        .where(latest_edit_at.is_not(None), Document.updated_at < latest_edit_at)
        .values(updated_at=latest_edit_at)
    )
    return max(0, int(result.rowcount or 0))
