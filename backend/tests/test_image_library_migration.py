from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import app.models  # noqa: F401 - registers all tables used by migrate_schema.
from sqlalchemy import create_engine, inspect, text

from app import bootstrap
from app.db.base import Base
from tests.workspace_temp import WorkspaceTempDirectory


class ImageLibraryMigrationTests(unittest.TestCase):
    def test_legacy_image_generation_table_gets_timeout_default_idempotently(self) -> None:
        with WorkspaceTempDirectory("image-library-migration") as temp_dir:
            database_path = Path(temp_dir) / "legacy-generation.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE image_generations"))
                connection.execute(
                    text(
                        "CREATE TABLE image_generations ("
                        "id VARCHAR(36) PRIMARY KEY, quality VARCHAR(24) NOT NULL DEFAULT 'auto')"
                    )
                )
                connection.execute(text("INSERT INTO image_generations (id) VALUES ('legacy-generation')"))

            with patch.object(bootstrap, "engine", engine):
                bootstrap.migrate_schema()
                bootstrap.migrate_schema()

            columns = {column["name"] for column in inspect(engine).get_columns("image_generations")}
            self.assertIn("timeout_seconds", columns)
            with engine.connect() as connection:
                timeout_seconds = connection.execute(
                    text("SELECT timeout_seconds FROM image_generations WHERE id = 'legacy-generation'")
                ).scalar_one()
            self.assertEqual(timeout_seconds, 180)
            engine.dispose()

    def test_half_built_sqlite_table_gets_library_lifecycle_columns_idempotently(self) -> None:
        with WorkspaceTempDirectory("image-library-migration") as temp_dir:
            database_path = Path(temp_dir) / "half-built.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE image_library_assets"))
                connection.execute(
                    text(
                        "CREATE TABLE image_library_assets ("
                        "id VARCHAR(36) PRIMARY KEY, owner_id INTEGER NOT NULL, document_id INTEGER, "
                        "generation_id VARCHAR(36) NOT NULL DEFAULT '', "
                        "generated_asset_id VARCHAR(36) NOT NULL DEFAULT '', "
                        "name VARCHAR(256) NOT NULL DEFAULT 'image', source VARCHAR(16) NOT NULL DEFAULT 'upload', "
                        "object_key VARCHAR(512) NOT NULL UNIQUE, storage_mode VARCHAR(12) NOT NULL, "
                        "url VARCHAR(4096) NOT NULL, content_type VARCHAR(64) NOT NULL, size INTEGER NOT NULL, "
                        "width INTEGER NOT NULL DEFAULT 0, height INTEGER NOT NULL DEFAULT 0, "
                        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO image_library_assets "
                        "(id, owner_id, object_key, storage_mode, url, content_type, size, created_at) "
                        "VALUES ('legacy-asset', 1, 'legacy/image.png', 'local', '/legacy/image.png', "
                        "'image/png', 12, '2026-08-01 12:00:00')"
                    )
                )

            with patch.object(bootstrap, "engine", engine):
                bootstrap.migrate_schema()
                bootstrap.migrate_schema()

            inspector = inspect(engine)
            columns = {column["name"] for column in inspector.get_columns("image_library_assets")}
            indexes = {index["name"] for index in inspector.get_indexes("image_library_assets")}
            self.assertTrue({"is_shared", "deleted_at", "updated_at"}.issubset(columns))
            self.assertTrue(
                {"ix_image_library_assets_is_shared", "ix_image_library_assets_deleted_at"}.issubset(indexes)
            )
            with engine.connect() as connection:
                migrated = connection.execute(
                    text("SELECT is_shared, deleted_at, created_at, updated_at FROM image_library_assets")
                ).mappings().one()
            self.assertEqual(migrated["is_shared"], 0)
            self.assertIsNone(migrated["deleted_at"])
            self.assertEqual(migrated["updated_at"], migrated["created_at"])
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
