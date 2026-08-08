from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, or_
from sqlalchemy.orm import Query as SqlAlchemyQuery
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.api.routes.documents import _set_ai_editing_statuses
from app.db.session import get_db
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.user import User
from app.schemas.document import DocumentGroupRead, DocumentSummary
from app.schemas.workbench import (
    DocumentPageRead,
    WorkbenchDocumentPageRead,
    WorkbenchDocumentSummary,
    WorkbenchGroupedRead,
    WorkbenchGroupItemRead,
    WorkbenchGroupPageRead,
)
from app.services.document_access import accessible_document_groups_query, accessible_documents_query

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

DEFAULT_GROUP_PAGE_SIZE = 10
DEFAULT_DOCUMENT_PAGE_SIZE = 20
DEFAULT_GROUP_DOCUMENT_PAGE_SIZE = 5
MAX_GROUP_PAGE_SIZE = 50
MAX_DOCUMENT_PAGE_SIZE = 100


def _document_options(query: SqlAlchemyQuery) -> SqlAlchemyQuery:
    return query.options(
        selectinload(Document.created_by),
        selectinload(Document.last_modified_by),
        selectinload(Document.allowed_users),
        selectinload(Document.allowed_groups),
    )


def _document_page(query: SqlAlchemyQuery, db: Session, page: int, page_size: int) -> DocumentPageRead:
    total = query.order_by(None).count()
    documents = (
        _document_options(query)
        .order_by(desc(Document.updated_at), Document.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return DocumentPageRead(
        items=_set_ai_editing_statuses(db, documents),
        total=total,
        page=page,
        page_size=page_size,
    )


def _accessible_documents(db: Session, user: User) -> SqlAlchemyQuery:
    return accessible_documents_query(db.query(Document), user)


def _accessible_group(db: Session, group_id: int, user: User) -> DocumentGroup:
    group = accessible_document_groups_query(db.query(DocumentGroup), user).filter(DocumentGroup.id == group_id).first()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    return group


@router.get("/groups", response_model=WorkbenchGroupedRead)
def list_workbench_groups(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_GROUP_PAGE_SIZE, ge=1, le=MAX_GROUP_PAGE_SIZE),
    document_page_size: int = Query(DEFAULT_GROUP_DOCUMENT_PAGE_SIZE, ge=1, le=MAX_DOCUMENT_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkbenchGroupedRead:
    groups_query = accessible_document_groups_query(db.query(DocumentGroup), current_user)
    group_total = groups_query.order_by(None).count()
    groups = (
        groups_query.options(
            selectinload(DocumentGroup.owner),
            selectinload(DocumentGroup.last_modified_by),
            selectinload(DocumentGroup.allowed_users),
            selectinload(DocumentGroup.allowed_groups),
        )
        .order_by(desc(DocumentGroup.updated_at), DocumentGroup.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for group in groups:
        documents = _document_page(
            _accessible_documents(db, current_user).filter(Document.group_id == group.id),
            db,
            1,
            document_page_size,
        )
        items.append(
            WorkbenchGroupItemRead(
                group=DocumentGroupRead.model_validate(group),
                document_total=documents.total,
                documents=documents,
            )
        )
    ungrouped = _document_page(
        _accessible_documents(db, current_user).filter(Document.group_id.is_(None)),
        db,
        1,
        document_page_size,
    )
    return WorkbenchGroupedRead(
        groups=WorkbenchGroupPageRead(items=items, total=group_total, page=page, page_size=page_size),
        ungrouped=ungrouped,
    )


@router.get("/groups/{group_id}/documents", response_model=DocumentPageRead)
def list_group_documents(
    group_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_GROUP_DOCUMENT_PAGE_SIZE, ge=1, le=MAX_DOCUMENT_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentPageRead:
    _accessible_group(db, group_id, current_user)
    return _document_page(_accessible_documents(db, current_user).filter(Document.group_id == group_id), db, page, page_size)


@router.get("/ungrouped/documents", response_model=DocumentPageRead)
def list_ungrouped_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_GROUP_DOCUMENT_PAGE_SIZE, ge=1, le=MAX_DOCUMENT_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentPageRead:
    return _document_page(_accessible_documents(db, current_user).filter(Document.group_id.is_(None)), db, page, page_size)


@router.get("/documents", response_model=WorkbenchDocumentPageRead)
def list_workbench_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_DOCUMENT_PAGE_SIZE, ge=1, le=MAX_DOCUMENT_PAGE_SIZE),
    query: str = Query("", max_length=256),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkbenchDocumentPageRead:
    documents_query = _accessible_documents(db, current_user).outerjoin(DocumentGroup, Document.group_id == DocumentGroup.id)
    keyword = query.strip()
    if keyword:
        pattern = f"%{keyword}%"
        documents_query = documents_query.filter(or_(Document.title.ilike(pattern), DocumentGroup.name.ilike(pattern)))

    total = documents_query.order_by(None).count()
    rows = (
        _document_options(documents_query)
        .add_columns(DocumentGroup.name.label("group_name"))
        .order_by(desc(Document.updated_at), Document.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    documents = _set_ai_editing_statuses(db, [document for document, _group_name in rows])
    items = []
    for document, (_row_document, group_name) in zip(documents, rows, strict=True):
        payload = DocumentSummary.model_validate(document).model_dump()
        items.append(WorkbenchDocumentSummary(**payload, group_name=group_name))
    return WorkbenchDocumentPageRead(items=items, total=total, page=page, page_size=page_size)
