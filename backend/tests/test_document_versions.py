import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.routes import documents
from app.db.base import Base
from app.models.document import Document
from app.models.document_content_object import DocumentContentObject
from app.models.document_group import DocumentGroup
from app.models.document_visibility import VisibilityMode
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.user import User, UserRole
from app.schemas.document import DocumentHtmlPatch, DocumentVersionCopyCreate
from app.services.document_versions import (
    DELTA,
    MAX_DELTA_DEPTH,
    SNAPSHOT,
    DocumentVersionStorageError,
    content_checksum,
    create_document_version,
    make_single_splice,
    materialize_document_version,
)


class DocumentVersionStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            username="versioner",
            display_name="Versioner",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def make_document(self, html: str) -> Document:
        document = Document(
            owner_id=self.user.id,
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
            title="版本测试",
            current_html=html,
        )
        self.db.add(document)
        self.db.flush()
        return document

    @staticmethod
    def large_html() -> str:
        paragraphs = [f"<p data-index='{index}'>正文 {index:04d} - {index * 7919:08x}</p>" for index in range(900)]
        return "<section>" + "".join(paragraphs) + "</section>"

    def test_reuses_identical_content_and_reconstructs_delta(self) -> None:
        base_html = self.large_html()
        document = self.make_document(base_html)
        first = create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.flush()

        document.current_html = base_html.replace("正文 0450", "正文 已修改", 1)
        second = create_document_version(self.db, document, self.user.id, DocumentVersionSource.MANUAL, "修改")
        self.db.flush()

        second_object = self.db.get(DocumentContentObject, second.content_object_id)
        self.assertIsNotNone(second_object)
        assert second_object is not None
        self.assertEqual(second_object.storage_kind, DELTA)
        self.assertEqual(materialize_document_version(self.db, second), document.current_html)

        document.title = "仅改标题"
        third = create_document_version(self.db, document, self.user.id, DocumentVersionSource.MANUAL, "改标题")
        self.db.flush()
        self.assertEqual(third.content_object_id, second.content_object_id)
        self.assertEqual(self.db.query(DocumentContentObject).count(), 2)
        self.assertNotEqual(first.content_object_id, second.content_object_id)

    def test_limits_delta_replay_depth_with_a_new_snapshot(self) -> None:
        document = self.make_document(self.large_html())
        create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.flush()

        commits: list[DocumentVersion] = []
        for index in range(MAX_DELTA_DEPTH + 1):
            document.current_html = document.current_html.replace(
                f"正文 {index:04d}", f"变更 {index:04d}", 1
            )
            commits.append(create_document_version(self.db, document, self.user.id, DocumentVersionSource.MANUAL, "修改"))
            self.db.flush()

        last_delta_object = self.db.get(DocumentContentObject, commits[MAX_DELTA_DEPTH - 1].content_object_id)
        reset_snapshot_object = self.db.get(DocumentContentObject, commits[MAX_DELTA_DEPTH].content_object_id)
        self.assertEqual(last_delta_object.storage_kind, DELTA)
        self.assertEqual(last_delta_object.delta_depth, MAX_DELTA_DEPTH)
        self.assertEqual(reset_snapshot_object.storage_kind, SNAPSHOT)
        self.assertEqual(reset_snapshot_object.delta_depth, 0)
        self.assertEqual(materialize_document_version(self.db, commits[-1]), document.current_html)

    def test_content_patch_accepts_unicode_code_point_offsets(self) -> None:
        base_html = "<p>前😀旧文</p>"
        next_html = "<p>前😀新文</p>"
        document = self.make_document(base_html)
        create_document_version(self.db, document, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.commit()

        prefix_length, suffix_length, replacement = make_single_splice(base_html, next_html)
        result = documents.patch_document_content(
            document.id,
            DocumentHtmlPatch(
                base_checksum=content_checksum(base_html),
                prefix_length=prefix_length,
                suffix_length=suffix_length,
                replacement=replacement,
            ),
            self.user,
            self.db,
        )
        self.assertIsNone(result)
        self.db.refresh(document)
        self.assertEqual(document.current_html, next_html)
        latest = (
            self.db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number.desc())
            .first()
        )
        self.assertEqual(materialize_document_version(self.db, latest), next_html)
        detail = documents.get_document_version(document.id, latest.id, self.user, self.db)
        self.assertEqual(detail.html, next_html)

    def test_copy_creates_independent_document_from_non_latest_delta_version(self) -> None:
        base_html = self.large_html()
        source = self.make_document(base_html)
        create_document_version(self.db, source, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.flush()

        historical_html = base_html.replace("正文 0450", "历史正文 0450", 1)
        source.title = "历史标题"
        source.current_html = historical_html
        historical_version = create_document_version(self.db, source, self.user.id, DocumentVersionSource.MANUAL, "历史修改")
        self.db.flush()
        historical_object = self.db.get(DocumentContentObject, historical_version.content_object_id)
        self.assertIsNotNone(historical_object)
        assert historical_object is not None
        self.assertEqual(historical_object.storage_kind, DELTA)

        source.title = "最新标题"
        source.current_html = historical_html.replace("正文 0700", "最新正文 0700", 1)
        create_document_version(self.db, source, self.user.id, DocumentVersionSource.MANUAL, "后续修改")
        group = DocumentGroup(owner_id=self.user.id, name="复制目标", visibility_mode=VisibilityMode.ALL)
        self.db.add(group)
        self.db.commit()

        copied = documents.copy_document_version(
            source.id,
            historical_version.id,
            DocumentVersionCopyCreate(
                title="历史标题副本",
                group_id=group.id,
                visibility_mode="restricted",
                allowed_user_ids=[self.user.id],
                allowed_group_ids=[],
            ),
            self.user,
            self.db,
        )

        self.db.refresh(source)
        self.db.refresh(copied)
        self.assertNotEqual(copied.id, source.id)
        self.assertEqual(copied.owner_id, self.user.id)
        self.assertEqual(copied.created_by_id, self.user.id)
        self.assertEqual(copied.last_modified_by_id, self.user.id)
        self.assertEqual(copied.title, "历史标题副本")
        self.assertEqual(copied.current_html, historical_html)
        self.assertEqual(copied.group_id, group.id)
        self.assertEqual(copied.visibility_mode, VisibilityMode.RESTRICTED)
        self.assertEqual(copied.allowed_user_ids, [self.user.id])
        self.assertFalse(copied.has_source_file)
        self.assertEqual(source.title, "最新标题")
        self.assertIn("最新正文 0700", source.current_html)

        copied_version = (
            self.db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == copied.id)
            .one()
        )
        self.assertEqual(copied_version.version_number, 1)
        self.assertEqual(copied_version.source, DocumentVersionSource.INITIAL)
        self.assertEqual(copied_version.label, f"从 v{historical_version.version_number} 复制创建")
        self.assertEqual(copied_version.content_object_id, historical_version.content_object_id)
        self.assertEqual(materialize_document_version(self.db, copied_version), historical_html)

    def test_copy_rejects_version_from_another_document_without_creating_target(self) -> None:
        source = self.make_document("<p>源文章</p>")
        create_document_version(self.db, source, self.user.id, DocumentVersionSource.INITIAL, "创建")
        other = self.make_document("<p>另一篇文章</p>")
        foreign_version = create_document_version(self.db, other, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.commit()

        with self.assertRaises(HTTPException) as context:
            documents.copy_document_version(
                source.id,
                foreign_version.id,
                DocumentVersionCopyCreate(title="不应创建"),
                self.user,
                self.db,
            )

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(self.db.query(Document).count(), 2)

    def test_copy_rejects_inaccessible_source_and_target_group(self) -> None:
        other_user = User(
            username="source-owner",
            display_name="Source Owner",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(other_user)
        self.db.flush()
        private_source = Document(
            owner_id=other_user.id,
            created_by_id=other_user.id,
            last_modified_by_id=other_user.id,
            title="私有文章",
            current_html="<p>私有内容</p>",
            visibility_mode=VisibilityMode.RESTRICTED,
        )
        private_source.allowed_users = [other_user]
        self.db.add(private_source)
        self.db.flush()
        private_version = create_document_version(self.db, private_source, other_user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.commit()

        with self.assertRaises(HTTPException) as context:
            documents.copy_document_version(
                private_source.id,
                private_version.id,
                DocumentVersionCopyCreate(title="不应创建"),
                self.user,
                self.db,
            )
        self.assertEqual(context.exception.status_code, 404)

        source = self.make_document("<p>可访问文章</p>")
        source_version = create_document_version(self.db, source, self.user.id, DocumentVersionSource.INITIAL, "创建")
        inaccessible_group = DocumentGroup(
            owner_id=other_user.id,
            name="私有分组",
            visibility_mode=VisibilityMode.RESTRICTED,
        )
        inaccessible_group.allowed_users = [other_user]
        self.db.add(inaccessible_group)
        self.db.commit()
        document_count = self.db.query(Document).count()

        with self.assertRaises(HTTPException) as context:
            documents.copy_document_version(
                source.id,
                source_version.id,
                DocumentVersionCopyCreate(title="不应创建", group_id=inaccessible_group.id),
                self.user,
                self.db,
            )
        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(self.db.query(Document).count(), document_count)

    def test_copy_does_not_create_target_when_version_content_is_unreadable(self) -> None:
        source = self.make_document("<p>源文章</p>")
        version = create_document_version(self.db, source, self.user.id, DocumentVersionSource.INITIAL, "创建")
        self.db.commit()

        with patch.object(documents, "materialize_document_version", side_effect=DocumentVersionStorageError("损坏")):
            with self.assertRaises(HTTPException) as context:
                documents.copy_document_version(
                    source.id,
                    version.id,
                    DocumentVersionCopyCreate(title="不应创建"),
                    self.user,
                    self.db,
                )

        self.assertEqual(context.exception.status_code, 500)
        self.assertEqual(self.db.query(Document).count(), 1)


if __name__ == "__main__":
    unittest.main()
