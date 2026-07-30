import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.routes import document_groups, documents
from app.db.base import Base
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole
from app.schemas.document import DocumentGroupUpdate, DocumentUpdate


class DocumentManagementPermissionsTests(unittest.TestCase):
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
        user = User(
            username=username,
            display_name=username,
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def _create_document(
        self,
        *,
        visibility_mode: VisibilityMode = VisibilityMode.ALL,
        group: DocumentGroup | None = None,
    ) -> Document:
        document = Document(
            owner_id=self.owner.id,
            created_by_id=self.owner.id,
            last_modified_by_id=self.owner.id,
            title="协作推文",
            current_html="<p>正文</p>",
            visibility_mode=visibility_mode,
            group=group,
        )
        if visibility_mode == VisibilityMode.RESTRICTED:
            document.allowed_users.append(self.collaborator)
        self.db.add(document)
        self.db.commit()
        return document

    def _create_group(self, visibility_mode: VisibilityMode = VisibilityMode.ALL) -> DocumentGroup:
        group = DocumentGroup(owner_id=self.owner.id, name="协作分组", visibility_mode=visibility_mode)
        if visibility_mode == VisibilityMode.RESTRICTED:
            group.allowed_users.append(self.collaborator)
        self.db.add(group)
        self.db.commit()
        return group

    def test_collaborator_can_manage_a_public_document(self) -> None:
        document = self._create_document()
        target_group = self._create_group()

        documents.update_document(document.id, DocumentUpdate(group_id=target_group.id), self.collaborator, self.db)
        self.db.refresh(document)
        self.assertEqual(document.group_id, target_group.id)
        documents.delete_document(document.id, self.collaborator, self.db)

        self.assertIsNone(self.db.get(Document, document.id))

    def test_collaborator_can_manage_a_restricted_document_when_explicitly_authorized(self) -> None:
        document = self._create_document(visibility_mode=VisibilityMode.RESTRICTED)

        documents.delete_document(document.id, self.collaborator, self.db)

        self.assertIsNone(self.db.get(Document, document.id))

    def test_user_without_visibility_access_cannot_manage_a_restricted_document(self) -> None:
        document = self._create_document(visibility_mode=VisibilityMode.RESTRICTED)

        with self.assertRaises(HTTPException) as context:
            documents.delete_document(document.id, self.outsider, self.db)

        self.assertEqual(context.exception.status_code, 404)
        self.assertIsNotNone(self.db.get(Document, document.id))

    def test_collaborator_can_manage_a_document_in_a_restricted_group_when_explicitly_authorized(self) -> None:
        group = self._create_group(VisibilityMode.RESTRICTED)
        document = self._create_document(group=group)

        documents.delete_document(document.id, self.collaborator, self.db)

        self.assertIsNone(self.db.get(Document, document.id))

    def test_collaborator_can_manage_a_group_but_not_change_its_visibility(self) -> None:
        group = self._create_group(VisibilityMode.RESTRICTED)

        document_groups.update_group(group.id, DocumentGroupUpdate(name="已重命名"), self.collaborator, self.db)

        self.db.refresh(group)
        self.assertEqual(group.name, "已重命名")
        with self.assertRaises(HTTPException) as context:
            document_groups.update_group(
                group.id,
                DocumentGroupUpdate(visibility_mode="restricted"),
                self.collaborator,
                self.db,
            )

        self.assertEqual(context.exception.status_code, 403)

    def test_collaborator_can_delete_an_accessible_group(self) -> None:
        group = self._create_group(VisibilityMode.RESTRICTED)

        document_groups.delete_group(group.id, self.collaborator, self.db)

        self.assertIsNone(self.db.get(DocumentGroup, group.id))

    def test_collaborator_cannot_change_document_visibility(self) -> None:
        document = self._create_document()

        with self.assertRaises(HTTPException) as context:
            documents.update_document(
                document.id,
                DocumentUpdate(visibility_mode="restricted"),
                self.collaborator,
                self.db,
            )

        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
