from datetime import datetime, timezone

from app.models.document import Document
from app.models.document_group import DocumentGroup


def touch_document(document: Document, user_id: int) -> None:
    document.last_modified_by_id = user_id
    document.updated_at = datetime.now(timezone.utc)


def touch_group(group: DocumentGroup, user_id: int) -> None:
    group.last_modified_by_id = user_id
    group.updated_at = datetime.now(timezone.utc)
