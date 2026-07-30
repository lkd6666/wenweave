from __future__ import annotations

import base64
import hashlib
import json
import zlib

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_content_object import DocumentContentObject
from app.models.document_version import DocumentVersion, DocumentVersionSource

SNAPSHOT = "snapshot"
DELTA = "delta"
MAX_DELTA_DEPTH = 20
# Do not keep a delta unless it materially beats a compressed full snapshot.
MAX_DELTA_TO_SNAPSHOT_RATIO = 0.85


class DocumentVersionStorageError(RuntimeError):
    """Raised when an immutable version object cannot be reconstructed."""


def content_checksum(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def make_single_splice(base_html: str, next_html: str) -> tuple[int, int, str]:
    """Return a compact copy/copy/insert delta using Unicode code-point offsets."""
    prefix_length = 0
    common_length = min(len(base_html), len(next_html))
    while prefix_length < common_length and base_html[prefix_length] == next_html[prefix_length]:
        prefix_length += 1

    suffix_length = 0
    base_remaining = len(base_html) - prefix_length
    next_remaining = len(next_html) - prefix_length
    while (
        suffix_length < base_remaining
        and suffix_length < next_remaining
        and base_html[len(base_html) - suffix_length - 1] == next_html[len(next_html) - suffix_length - 1]
    ):
        suffix_length += 1

    end = len(next_html) - suffix_length if suffix_length else len(next_html)
    return prefix_length, suffix_length, next_html[prefix_length:end]


def apply_single_splice(base_html: str, prefix_length: int, suffix_length: int, replacement: str) -> str:
    if prefix_length < 0 or suffix_length < 0 or prefix_length + suffix_length > len(base_html):
        raise DocumentVersionStorageError("版本增量的偏移量无效")
    suffix = base_html[len(base_html) - suffix_length :] if suffix_length else ""
    return f"{base_html[:prefix_length]}{replacement}{suffix}"


def _encode(value: str) -> str:
    return base64.b64encode(zlib.compress(value.encode("utf-8"), level=6)).decode("ascii")


def _decode(payload: str) -> str:
    try:
        return zlib.decompress(base64.b64decode(payload.encode("ascii"))).decode("utf-8")
    except (UnicodeDecodeError, ValueError, zlib.error) as exc:
        raise DocumentVersionStorageError("版本内容对象已损坏") from exc


def _snapshot_payload(html: str) -> str:
    return _encode(html)


def _delta_payload(base_html: str, next_html: str) -> str:
    prefix_length, suffix_length, replacement = make_single_splice(base_html, next_html)
    return _encode(
        json.dumps(
            {"prefix_length": prefix_length, "suffix_length": suffix_length, "replacement": replacement},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _decode_delta(payload: str) -> tuple[int, int, str]:
    try:
        data = json.loads(_decode(payload))
        prefix_length = data["prefix_length"]
        suffix_length = data["suffix_length"]
        replacement = data["replacement"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DocumentVersionStorageError("版本增量对象已损坏") from exc
    if not isinstance(prefix_length, int) or not isinstance(suffix_length, int) or not isinstance(replacement, str):
        raise DocumentVersionStorageError("版本增量对象格式无效")
    return prefix_length, suffix_length, replacement


def materialize_content_object(db: Session, object_id: int) -> str:
    """Reconstruct one immutable content object, validating its content hash."""
    objects: list[DocumentContentObject] = []
    current_id: int | None = object_id
    visited: set[int] = set()

    while current_id is not None:
        if current_id in visited:
            raise DocumentVersionStorageError("版本内容对象存在循环引用")
        visited.add(current_id)
        content_object = db.get(DocumentContentObject, current_id)
        if not content_object:
            raise DocumentVersionStorageError("版本内容对象不存在")
        objects.append(content_object)
        if content_object.storage_kind == SNAPSHOT:
            html = _decode(content_object.payload)
            break
        if content_object.storage_kind != DELTA or content_object.base_object_id is None:
            raise DocumentVersionStorageError("版本内容对象类型无效")
        current_id = content_object.base_object_id
    else:
        raise DocumentVersionStorageError("版本内容对象缺少快照基线")

    for content_object in reversed(objects[:-1]):
        prefix_length, suffix_length, replacement = _decode_delta(content_object.payload)
        html = apply_single_splice(html, prefix_length, suffix_length, replacement)

    target = objects[0]
    if content_checksum(html) != target.checksum:
        raise DocumentVersionStorageError("版本内容校验失败")
    return html


def materialize_document_version(db: Session, version: DocumentVersion) -> str:
    """Read both new content-addressed commits and legacy full HTML snapshots."""
    if version.content_object_id is None:
        return version.html
    return materialize_content_object(db, version.content_object_id)


def _latest_version(db: Session, document_id: int) -> DocumentVersion | None:
    return (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )


def _store_content_object(db: Session, html: str, previous: DocumentVersion | None) -> DocumentContentObject:
    checksum = content_checksum(html)
    existing = db.query(DocumentContentObject).filter(DocumentContentObject.checksum == checksum).first()
    if existing:
        return existing

    snapshot_payload = _snapshot_payload(html)
    storage_kind = SNAPSHOT
    payload = snapshot_payload
    base_object_id: int | None = None
    delta_depth = 0

    if previous and previous.content_object_id is not None:
        previous_object = db.get(DocumentContentObject, previous.content_object_id)
        if previous_object and previous_object.delta_depth < MAX_DELTA_DEPTH:
            previous_html = materialize_document_version(db, previous)
            delta_payload = _delta_payload(previous_html, html)
            if len(delta_payload) < len(snapshot_payload) * MAX_DELTA_TO_SNAPSHOT_RATIO:
                storage_kind = DELTA
                payload = delta_payload
                base_object_id = previous_object.id
                delta_depth = previous_object.delta_depth + 1

    content_object = DocumentContentObject(
        checksum=checksum,
        storage_kind=storage_kind,
        payload=payload,
        base_object_id=base_object_id,
        delta_depth=delta_depth,
        html_size=len(html.encode("utf-8")),
    )
    db.add(content_object)
    db.flush()
    return content_object


def create_document_version(
    db: Session,
    document: Document,
    user_id: int | None,
    source: DocumentVersionSource,
    label: str,
) -> DocumentVersion:
    """Create a Git-style commit that references a deduplicated immutable object."""
    # Version numbers are per-document.  Lock the parent even for callers
    # that reached this helper through a legacy/non-patch route so MAX + 1 is
    # never evaluated concurrently.
    locked_document = db.query(Document).filter(Document.id == document.id).with_for_update().first()
    if locked_document is None:
        raise DocumentVersionStorageError("文档不存在，无法创建版本")
    document = locked_document
    db.flush()
    previous = _latest_version(db, document.id)
    content_object = _store_content_object(db, document.current_html, previous)
    last_number = (
        db.query(func.max(DocumentVersion.version_number))
        .filter(DocumentVersion.document_id == document.id)
        .scalar()
    )
    version = DocumentVersion(
        document_id=document.id,
        version_number=(last_number or 0) + 1,
        title=document.title,
        html="",
        content_object_id=content_object.id,
        source=source,
        label=label[:256],
        created_by_id=user_id,
    )
    db.add(version)
    return version


def migrate_legacy_document_versions(db: Session) -> int:
    """Move old full-copy version rows into the object store exactly once."""
    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.content_object_id.is_(None))
        .order_by(DocumentVersion.document_id, DocumentVersion.version_number)
        .all()
    )
    previous_by_document: dict[int, DocumentVersion] = {}
    migrated = 0
    for version in versions:
        previous = previous_by_document.get(version.document_id)
        content_object = _store_content_object(db, version.html, previous)
        version.content_object_id = content_object.id
        version.html = ""
        previous_by_document[version.document_id] = version
        migrated += 1
    return migrated
