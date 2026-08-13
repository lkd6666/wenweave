import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.functions import Function

import app.models  # noqa: F401
from app.db.base import Base
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.user import User, UserRole
from app.services.document_activity import repair_document_activity_timestamps, touch_document, touch_group


class DocumentActivityTests(unittest.TestCase):
    def test_touch_document_uses_database_clock(self) -> None:
        document = Document(owner_id=1, title="文章", current_html="")

        touch_document(document, 7)

        self.assertEqual(document.last_modified_by_id, 7)
        self.assertIsInstance(document.updated_at, Function)
        self.assertEqual(document.updated_at.name, "now")

    def test_touch_group_uses_database_clock(self) -> None:
        group = DocumentGroup(owner_id=1, name="分组")

        touch_group(group, 9)

        self.assertEqual(group.last_modified_by_id, 9)
        self.assertIsInstance(group.updated_at, Function)
        self.assertEqual(group.updated_at.name, "now")

    def test_repair_uses_latest_real_edit_but_ignores_initial_version(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            user = User(
                username="editor",
                display_name="Editor",
                password_hash="not-used",
                role=UserRole.USER,
                is_active=True,
            )
            session.add(user)
            session.flush()
            edited = Document(
                owner_id=user.id,
                created_by_id=user.id,
                last_modified_by_id=user.id,
                title="已编辑",
                current_html="<p>正文</p>",
                updated_at=datetime(2026, 8, 10, 12, 21, 33),
            )
            initial_only = Document(
                owner_id=user.id,
                created_by_id=user.id,
                last_modified_by_id=user.id,
                title="仅导入",
                current_html="<p>原稿</p>",
                updated_at=datetime(2026, 8, 10, 12, 30, 0),
            )
            session.add_all((edited, initial_only))
            session.flush()
            session.add_all(
                (
                    DocumentVersion(
                        document_id=edited.id,
                        version_number=1,
                        title=edited.title,
                        source=DocumentVersionSource.AI,
                        label="AI 编辑",
                        created_at=datetime(2026, 8, 10, 20, 21, 33),
                    ),
                    DocumentVersion(
                        document_id=initial_only.id,
                        version_number=1,
                        title=initial_only.title,
                        source=DocumentVersionSource.INITIAL,
                        label="导入",
                        created_at=datetime(2026, 8, 10, 20, 30, 0),
                    ),
                )
            )
            session.commit()

            with engine.begin() as connection:
                repaired = repair_document_activity_timestamps(connection)

            session.expire_all()
            self.assertEqual(repaired, 1)
            self.assertEqual(session.get(Document, edited.id).updated_at, datetime(2026, 8, 10, 20, 21, 33))
            self.assertEqual(session.get(Document, initial_only.id).updated_at, datetime(2026, 8, 10, 12, 30, 0))
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
