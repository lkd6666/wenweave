import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.routes import documents
from app.db.base import Base
from app.models.document_import import DocumentImport
from app.models.document_visibility import VisibilityMode
from app.models.storage_config import StorageConfig
from app.models.user import User, UserRole
from app.schemas.document import (
    DocumentImportAssetCreate,
    DocumentImportAssetsCreate,
    DocumentImportComplete,
    DocumentImportCreate,
)


class DirectImportRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            username="importer",
            display_name="Importer",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add_all(
            [
                self.user,
                StorageConfig(
                    endpoint="oss-cn-test.aliyuncs.com",
                    bucket="test-bucket",
                    access_key_id="test-id",
                    access_key_secret_encrypted="test-secret",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(self.user)

        self.sign_upload = patch(
            "app.api.routes.documents.oss_client.sign_direct_upload",
            side_effect=lambda _config, key, _content_type: f"https://upload.test/{key}",
        )
        self.sign_read = patch(
            "app.api.routes.documents.oss_client.sign_read_url",
            side_effect=lambda _config, key, _expires=0: f"https://read.test/{key}",
        )
        self.inspect = patch(
            "app.api.routes.documents.oss_client.inspect_object",
            side_effect=lambda _config, key: self.uploaded_objects[key],
        )
        self.delete = patch("app.api.routes.documents.oss_client.delete_object")
        self.sign_upload.start()
        self.sign_read.start()
        self.inspect.start()
        self.delete.start()
        self.uploaded_objects: dict[str, dict[str, object]] = {}

    def tearDown(self) -> None:
        self.sign_upload.stop()
        self.sign_read.stop()
        self.inspect.stop()
        self.delete.stop()
        self.db.close()
        self.engine.dispose()

    def test_direct_import_only_signs_fixed_keys_and_completes_once(self) -> None:
        started = documents.create_direct_import(
            DocumentImportCreate(
                filename="campaign.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size=1024,
            ),
            self.user,
            self.db,
        )
        self.assertIn(f"/direct-imports/{started.id}/source.docx", started.source_upload.object_key)
        self.assertNotIn("campaign", started.source_upload.object_key)

        assets = documents.create_direct_import_assets(
            started.id,
            DocumentImportAssetsCreate(
                assets=[
                    DocumentImportAssetCreate(
                        client_id="word-image-1",
                        filename="word-image-1.png",
                        content_type="image/png",
                        size=12,
                    )
                ]
            ),
            self.user,
            self.db,
        )
        self.assertEqual(len(assets.assets), 1)
        asset = assets.assets[0]
        self.assertIn(f"/assets/{asset.asset_id}.png", asset.upload.object_key)

        self.uploaded_objects[started.source_upload.object_key] = {
            "size": 1024,
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        self.uploaded_objects[asset.upload.object_key] = {"size": 12, "content_type": "image/png"}
        result = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html=f'<p><img src="direct-import://asset/{asset.asset_id}" /></p>'),
            self.user,
            self.db,
        )
        self.assertTrue(result.has_source_file)
        self.assertIn("https://read.test/", result.current_html)
        self.assertEqual(result.source_filename, "campaign.docx")

        repeated = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html=f'<p><img src="direct-import://asset/{asset.asset_id}" /></p>'),
            self.user,
            self.db,
        )
        self.assertEqual(repeated.id, result.id)
        self.assertEqual(self.db.query(DocumentImport).filter_by(id=started.id).one().document_id, result.id)

    def test_rejects_missing_or_forged_image_placeholders(self) -> None:
        started = documents.create_direct_import(
            DocumentImportCreate(filename="report.pdf", content_type="application/pdf", size=100),
            self.user,
            self.db,
        )
        self.uploaded_objects[started.source_upload.object_key] = {"size": 100, "content_type": "application/pdf"}
        with self.assertRaises(HTTPException) as context:
            documents.complete_direct_import(
                started.id,
                DocumentImportComplete(html='<p><img src="direct-import://asset/00000000-0000-0000-0000-000000000000" /></p>'),
                self.user,
                self.db,
            )
        self.assertEqual(context.exception.status_code, 400)

    def test_source_access_requires_document_permission(self) -> None:
        started = documents.create_direct_import(
            DocumentImportCreate(filename="report.pdf", content_type="application/pdf", size=100),
            self.user,
            self.db,
        )
        self.uploaded_objects[started.source_upload.object_key] = {"size": 100, "content_type": "application/pdf"}
        document = documents.complete_direct_import(
            started.id,
            DocumentImportComplete(html="<p>Report</p>"),
            self.user,
            self.db,
        )
        document.visibility_mode = VisibilityMode.RESTRICTED
        document.allowed_users.append(self.user)
        self.db.commit()
        access = documents.get_document_source_access(document.id, self.user, self.db)
        self.assertEqual(access.filename, "report.pdf")
        self.assertTrue(access.url.startswith("https://read.test/"))

        outsider = User(
            username="outsider",
            display_name="Outsider",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(outsider)
        self.db.commit()
        with self.assertRaises(HTTPException) as context:
            documents.get_document_source_access(document.id, outsider, self.db)
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
