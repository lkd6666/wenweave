import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.routes import workbench
from app.db.base import Base
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole


class WorkbenchPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.owner = self._create_user("owner")
        self.collaborator = self._create_user("collaborator")
        self.outsider = self._create_user("outsider")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _create_user(self, username: str) -> User:
        user = User(username=username, display_name=username, password_hash="not-used", role=UserRole.USER, is_active=True)
        self.db.add(user)
        self.db.flush()
        return user

    def _create_group(self, name: str, visibility: VisibilityMode = VisibilityMode.ALL) -> DocumentGroup:
        group = DocumentGroup(owner_id=self.owner.id, name=name, visibility_mode=visibility)
        self.db.add(group)
        self.db.flush()
        return group

    def _create_document(self, title: str, group: DocumentGroup | None = None, offset: int = 0) -> Document:
        document = Document(
            owner_id=self.owner.id,
            created_by_id=self.owner.id,
            last_modified_by_id=self.owner.id,
            title=title,
            current_html="<p>正文</p>",
            group=group,
            updated_at=datetime(2026, 8, 4, tzinfo=timezone.utc) + timedelta(minutes=offset),
        )
        self.db.add(document)
        self.db.flush()
        return document

    def test_grouped_page_contains_first_document_page_and_ungrouped_page(self) -> None:
        group = self._create_group("活动")
        for index in range(5):
            self._create_document(f"活动 {index}", group, index)
        self._create_document("未分组", None, 10)
        self.db.commit()

        result = workbench.list_workbench_groups(
            page=1,
            page_size=10,
            document_page_size=2,
            current_user=self.owner,
            db=self.db,
        )

        self.assertEqual(result.groups.total, 1)
        self.assertEqual(result.groups.items[0].document_total, 5)
        self.assertEqual(result.groups.items[0].documents.total, 5)
        self.assertEqual([item.title for item in result.groups.items[0].documents.items], ["活动 4", "活动 3"])
        self.assertEqual(result.ungrouped.total, 1)
        self.assertEqual(result.ungrouped.items[0].title, "未分组")

    def test_group_document_page_uses_stable_recent_first_order(self) -> None:
        group = self._create_group("日常")
        for index in range(5):
            self._create_document(f"文档 {index}", group, index)
        self.db.commit()

        result = workbench.list_group_documents(
            group.id,
            page=2,
            page_size=2,
            current_user=self.owner,
            db=self.db,
        )

        self.assertEqual((result.total, result.page, result.page_size), (5, 2, 2))
        self.assertEqual([item.title for item in result.items], ["文档 2", "文档 1"])

    def test_global_search_matches_group_name_and_includes_group_label(self) -> None:
        group = self._create_group("秋季活动")
        self._create_document("不含关键词的推文", group)
        self._create_document("秋季预告", None, 1)
        self.db.commit()

        result = workbench.list_workbench_documents(
            page=1,
            page_size=20,
            query="秋季",
            current_user=self.owner,
            db=self.db,
        )

        self.assertEqual(result.total, 2)
        labels = {item.title: item.group_name for item in result.items}
        self.assertEqual(labels["不含关键词的推文"], "秋季活动")
        self.assertIsNone(labels["秋季预告"])

    def test_restricted_group_is_excluded_from_counts_search_and_group_page(self) -> None:
        restricted_group = self._create_group("仅协作者", VisibilityMode.RESTRICTED)
        restricted_group.allowed_users.append(self.collaborator)
        self._create_document("保密推文", restricted_group)
        self._create_document("公开推文")
        self.db.commit()

        grouped = workbench.list_workbench_groups(
            page=1,
            page_size=10,
            document_page_size=20,
            current_user=self.outsider,
            db=self.db,
        )
        searched = workbench.list_workbench_documents(
            page=1,
            page_size=20,
            query="推文",
            current_user=self.outsider,
            db=self.db,
        )

        self.assertEqual(grouped.groups.total, 0)
        self.assertEqual(grouped.ungrouped.total, 1)
        self.assertEqual([item.title for item in searched.items], ["公开推文"])
        with self.assertRaises(HTTPException) as context:
            workbench.list_group_documents(
                restricted_group.id,
                page=1,
                page_size=20,
                current_user=self.outsider,
                db=self.db,
            )
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
