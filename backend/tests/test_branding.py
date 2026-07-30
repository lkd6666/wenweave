import asyncio
import io
import unittest
from types import SimpleNamespace

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.branding import (
    delete_branding_asset,
    get_branding,
    get_branding_asset,
    update_branding,
    upload_logo,
)
from app.db.base import Base
from app.models.user import User, UserRole
from app.schemas.branding import AppBrandingUpdate
from app.services.operation_logs import classify_operation


ONE_PIXEL_GIF = b"GIF89a\x01\x00\x01\x00"


class BrandingRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.admin = User(
            username="branding-admin",
            display_name="品牌管理员",
            password_hash="not-used",
            role=UserRole.ADMIN,
            is_active=True,
        )
        self.db.add(self.admin)
        self.db.commit()
        self.current_user = SimpleNamespace(id=self.admin.id, role=UserRole.ADMIN)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_public_read_uses_default_before_any_admin_update(self) -> None:
        branding = get_branding(db=self.db)

        self.assertEqual(branding["system_name"], "微信公众号 AI 排版系统")
        self.assertIsNone(branding["logo_url"])
        self.assertIsNone(branding["favicon_url"])

    def test_admin_can_update_name_upload_read_and_remove_logo(self) -> None:
        updated = update_branding(
            AppBrandingUpdate(system_name="  编辑器品牌  "),
            current_user=self.current_user,
            db=self.db,
        )
        self.assertEqual(updated["system_name"], "编辑器品牌")

        file = UploadFile(filename="brand.gif", file=io.BytesIO(ONE_PIXEL_GIF))
        uploaded = asyncio.run(upload_logo(file=file, current_user=self.current_user, db=self.db))
        self.assertEqual(uploaded["logo_url"], "/api/branding/assets/logo")
        self.assertEqual(uploaded["logo_content_type"], "image/gif")

        response = get_branding_asset("logo", db=self.db)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, ONE_PIXEL_GIF)
        self.assertEqual(response.media_type, "image/gif")

        removed = delete_branding_asset("logo", current_user=self.current_user, db=self.db)
        self.assertIsNone(removed["logo_url"])
        with self.assertRaises(HTTPException) as context:
            get_branding_asset("logo", db=self.db)
        self.assertEqual(context.exception.status_code, 404)

    def test_branding_mutations_have_specific_audit_actions(self) -> None:
        self.assertEqual(classify_operation("PUT", "/api/branding").action, "branding.update")
        self.assertEqual(classify_operation("POST", "/api/branding/logo").action, "branding.logo.upload")
        self.assertEqual(classify_operation("DELETE", "/api/branding/assets/favicon").action, "branding.favicon.delete")


if __name__ == "__main__":
    unittest.main()
