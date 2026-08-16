import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app import bootstrap
from app.api.deps import require_admin
from app.api.routes.article_typography import get_article_typography_settings, update_article_typography_settings
from app.db.base import Base
from app.models.user import User, UserRole
from app.schemas.article_typography import ArticleTypographySettingsUpdate
from app.services.operation_logs import classify_operation
from tests.workspace_temp import WorkspaceTempDirectory


class ArticleTypographySettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.admin = User(
            username="typography-admin",
            display_name="排版管理员",
            password_hash="not-used",
            role=UserRole.ADMIN,
            is_active=True,
        )
        self.user = User(
            username="typography-user",
            display_name="普通用户",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add_all([self.admin, self.user])
        self.db.commit()
        self.current_admin = SimpleNamespace(id=self.admin.id, role=UserRole.ADMIN)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_default_is_created_with_existing_body_style_values(self) -> None:
        settings = get_article_typography_settings(current_user=self.current_admin, db=self.db)

        self.assertEqual(settings["horizontal_padding_px"], 4)
        self.assertEqual(settings["paragraph_spacing_px"], 20)
        self.assertEqual(settings["font_size_px"], 15)
        self.assertEqual(settings["line_height_em"], 2)
        self.assertEqual(settings["letter_spacing_px"], 1)
        self.assertEqual(settings["text_indent_em"], 2)
        self.assertEqual(settings["text_color"], "#000000")

    def test_settings_payload_is_safe_for_agent_run_json_context(self) -> None:
        settings = get_article_typography_settings(current_user=self.current_admin, db=self.db)

        self.assertIsInstance(settings["updated_at"], str)
        json.dumps({"article_typography_settings": settings}, ensure_ascii=False)

    def test_admin_can_update_normalized_values(self) -> None:
        settings = update_article_typography_settings(
            ArticleTypographySettingsUpdate(
                horizontal_padding_px=12.5,
                paragraph_spacing_px=8,
                font_size_px=16.5,
                line_height_em=1.8,
                letter_spacing_px=0.5,
                text_indent_em=1.5,
                text_color="#1a2b3c",
            ),
            current_user=self.current_admin,
            db=self.db,
        )

        self.assertEqual(settings["text_color"], "#1A2B3C")
        self.assertEqual(settings["font_size_px"], 16.5)

    def test_invalid_ranges_colors_and_precision_are_rejected(self) -> None:
        data = {
            "horizontal_padding_px": 4,
            "paragraph_spacing_px": 20,
            "font_size_px": 15,
            "line_height_em": 2,
            "letter_spacing_px": 1,
            "text_indent_em": 2,
            "text_color": "#000000",
        }
        for patch in ({"horizontal_padding_px": 24.1}, {"text_color": "red"}, {"line_height_em": 2.25}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ArticleTypographySettingsUpdate(**{**data, **patch})

    def test_require_admin_rejects_regular_users(self) -> None:
        with self.assertRaises(HTTPException) as context:
            require_admin(current_user=self.user)
        self.assertEqual(context.exception.status_code, 403)

    def test_typography_updates_have_a_specific_audit_action(self) -> None:
        audit = classify_operation("PUT", "/api/article-typography-settings")
        self.assertEqual(audit.action, "typography_settings.update")
        self.assertEqual(audit.resource_type, "article_typography_settings")

    def test_startup_migration_initializes_the_singleton_idempotently(self) -> None:
        from unittest.mock import patch

        with WorkspaceTempDirectory("article-typography") as temp_dir:
            database_path = Path(temp_dir) / "typography-settings.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM article_typography_settings"))

            with patch.object(bootstrap, "engine", engine):
                bootstrap.migrate_schema()
                bootstrap.migrate_schema()

            with engine.connect() as connection:
                settings = connection.execute(
                    text(
                        "SELECT horizontal_padding_px, paragraph_spacing_px, font_size_px, "
                        "line_height_em, letter_spacing_px, text_indent_em, text_color "
                        "FROM article_typography_settings WHERE id = 1"
                    )
                ).mappings().one()
            engine.dispose()
        self.assertEqual(dict(settings), {
            "horizontal_padding_px": 4.0,
            "paragraph_spacing_px": 20.0,
            "font_size_px": 15.0,
            "line_height_em": 2.0,
            "letter_spacing_px": 1.0,
            "text_indent_em": 2.0,
            "text_color": "#000000",
        })


if __name__ == "__main__":
    unittest.main()
