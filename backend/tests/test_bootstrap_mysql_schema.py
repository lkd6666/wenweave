import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.bootstrap as bootstrap
from app.main import _schema_tables_before_image_model_access
from app.models.user_group import image_model_group_access, image_model_user_access
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


class _Rows:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def mappings(self) -> "_Rows":
        return self

    def all(self) -> list[dict[str, str]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement, _parameters=None) -> _Rows:
        sql = str(statement)
        self.statements.append(sql)
        if "information_schema.TABLES" in sql:
            return _Rows(
                [
                    {"TABLE_NAME": "ai_image_models", "ENGINE": "InnoDB"},
                    {"TABLE_NAME": "users", "ENGINE": "InnoDB"},
                    {"TABLE_NAME": "user_groups", "ENGINE": "MyISAM"},
                ]
            )
        if "information_schema.COLUMNS" in sql:
            return _Rows(
                [
                    {"TABLE_NAME": "ai_image_models", "COLUMN_TYPE": "bigint unsigned"},
                    {"TABLE_NAME": "users", "COLUMN_TYPE": "bigint unsigned"},
                    {"TABLE_NAME": "user_groups", "COLUMN_TYPE": "int unsigned"},
                ]
            )
        return _Rows([])


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Connection:
        return self.connection

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None


class _MySqlEngine:
    url = SimpleNamespace(drivername="mysql+pymysql")

    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def begin(self) -> _Transaction:
        return _Transaction(self.connection)


class MySqlImageModelAccessBootstrapTests(unittest.TestCase):
    def test_image_model_access_tables_explicitly_use_innodb(self) -> None:
        for table in (image_model_user_access, image_model_group_access):
            ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
            self.assertIn("ENGINE=InnoDB", ddl)

    def test_parent_schema_pass_excludes_image_model_access_tables(self) -> None:
        table_names = {table.name for table in _schema_tables_before_image_model_access()}

        self.assertNotIn("image_model_user_access", table_names)
        self.assertNotIn("image_model_group_access", table_names)
        self.assertIn("ai_image_models", table_names)
        self.assertIn("user_groups", table_names)

    def test_creates_legacy_access_tables_with_parent_id_types(self) -> None:
        connection = _Connection()
        engine = _MySqlEngine(connection)

        with patch.object(bootstrap, "engine", engine):
            bootstrap.prepare_mysql_image_model_access_tables()

        statements = "\n".join(connection.statements)
        self.assertIn("ALTER TABLE `user_groups` ENGINE=InnoDB", statements)
        self.assertIn("CREATE TABLE `image_model_user_access`", statements)
        self.assertIn("CREATE TABLE `image_model_group_access`", statements)
        self.assertIn("`group_id` int unsigned NOT NULL", statements)
        self.assertIn("FOREIGN KEY (`group_id`) REFERENCES `user_groups` (`id`)", statements)
