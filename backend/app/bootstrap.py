"""首次启动初始化逻辑与轻量 SQLite schema migration。"""
import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR, get_settings
from app.core.security import hash_password, is_forced_password_change_value, password_hash_requires_change
from app.core.token_budgets import DEFAULT_TOOL_RESULT_MAX_TOKENS
from app.db.session import engine
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_run_event import AgentRunEvent
from app.models.model_call_record import ModelCallRecord, ModelCallStatus
from app.models.chat_user_question import ChatUserQuestion
from app.models.chat_message import ChatMessage, MessageRole
from app.models.document import Document
from app.models.chat_session import ChatSession, ChatSessionMemory
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_context_snapshot import ChatContextSnapshot
from app.models.chat_history_archive import ChatHistoryArchive
from app.models.chat_tool_output import ChatToolOutput
from app.models.user import User, UserRole
from app.models.app_runtime_lock import AppRuntimeLock
from app.models.article_typography_settings import ArticleTypographySettings
from app.models.operation_log import OperationLogStatus
from app.models.schema_migration import SchemaMigration
from app.models.gzh_theme import GzhTheme, GzhThemeVersion
from app.services.document_activity import repair_document_activity_timestamps, touch_document, touch_group
from app.services.document_versions import create_document_version, migrate_legacy_document_versions
from app.services.operation_logs import append_operation_log
from app.services.agent_run_recovery import recover_interrupted_turn
from app.services.model_presets import (
    anthropic_adaptive_thinking_config,
    _gemini_25_thinking_config,
    _gemini_3_thinking_config,
    is_official_deepseek_openai_endpoint,
    official_deepseek_thinking_config,
)
from app.services.wechat_compliance import run_compliance_check


SCHEMA_REVISION = "20260816_password_change_policy_v1"
TOOL_PREVIEW_BUDGET_MIGRATION = "20260816_tool_preview_10000"
MYSQL_SCHEMA_LOCK_CONNECTION_TIMEOUT_SECONDS = 600


logger = logging.getLogger(__name__)


_MYSQL_IMAGE_MODEL_ACCESS_SPECS = (
    ("image_model_user_access", "user_id", "users"),
    ("image_model_group_access", "group_id", "user_groups"),
)


@contextmanager
def schema_migration_lock() -> Iterator[None]:
    """Serialize schema/bootstrap work across application workers.

    MySQL's advisory lock covers separate application processes.  SQLite and
    local development use a one-byte OS file lock because SQLite has no
    portable advisory-lock function that remains held across DDL connections.
    """
    settings = get_settings()
    timeout = max(1, int(settings.SCHEMA_MIGRATION_LOCK_TIMEOUT_SECONDS))
    if engine.url.drivername.startswith("mysql"):
        lock_name = "yibanpaiban:schema-migration"
        with engine.connect() as connection:
            acquired = connection.execute(
                text("SELECT GET_LOCK(:name, :timeout)"), {"name": lock_name, "timeout": timeout}
            ).scalar()
            if int(acquired or 0) != 1:
                raise RuntimeError("等待数据库 schema 迁移锁超时")
            # GET_LOCK belongs to this exact MySQL session.  Schema repair can
            # take longer than a locally configured wait_timeout, during which
            # the lock-owning connection is otherwise idle.  Keep it alive for
            # the entire bootstrap, so another worker cannot enter mid-migration.
            connection.execute(
                text("SET SESSION wait_timeout = :timeout"),
                {"timeout": MYSQL_SCHEMA_LOCK_CONNECTION_TIMEOUT_SECONDS},
            )
            try:
                yield
            finally:
                try:
                    connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
                except SQLAlchemyError:
                    # MySQL automatically releases advisory locks when their
                    # session closes.  A lost connection must not turn a fully
                    # completed migration into a failed application startup.
                    logger.warning("schema_migration_lock_release_failed", exc_info=True)
        return

    lock_path = engine.url.database
    # Keep the lock beside the local database when possible; a configured
    # SQLite URL otherwise still uses the project data directory deterministically.
    if not lock_path or lock_path == ":memory:":
        lock_file = DATA_DIR / ".schema-migration.lock"
    else:
        lock_file = Path(lock_path).resolve().parent / ".schema-migration.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("等待本地 schema 迁移锁超时")
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _mysql_image_model_access_create_sql(
    table_name: str,
    related_column_name: str,
    related_table_name: str,
    model_id_type: str,
    related_id_type: str,
) -> str:
    """Build a legacy-compatible association table with matching FK types."""

    def validated_column_type(value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized or not re.fullmatch(r"[A-Za-z0-9(), ]+", normalized):
            raise RuntimeError(f"不支持的 MySQL 主键类型：{value!r}")
        return normalized

    related_label = related_column_name.removesuffix("_id")
    return (
        f"CREATE TABLE `{table_name}` ("
        f"`model_id` {validated_column_type(model_id_type)} NOT NULL, "
        f"`{related_column_name}` {validated_column_type(related_id_type)} NOT NULL, "
        f"PRIMARY KEY (`model_id`, `{related_column_name}`), "
        f"CONSTRAINT `fk_{table_name}_model` FOREIGN KEY (`model_id`) "
        "REFERENCES `ai_image_models` (`id`) ON DELETE CASCADE, "
        f"CONSTRAINT `fk_{table_name}_{related_label}` FOREIGN KEY (`{related_column_name}`) "
        f"REFERENCES `{related_table_name}` (`id`) ON DELETE CASCADE"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


def prepare_mysql_image_model_access_tables() -> None:
    """Create image-model access tables safely against legacy MySQL parents.

    Early deployments could contain signed integer IDs or MyISAM parent tables.
    ``create_all`` normally creates the new association tables before the
    compatibility migrator runs, which makes MySQL reject those foreign keys
    and abort startup. Match the already-deployed parent column types here,
    before SQLAlchemy emits its static DDL.
    """

    if not engine.url.drivername.startswith("mysql"):
        return

    with engine.begin() as connection:
        table_rows = connection.execute(
            text(
                "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN "
                "('ai_image_models', 'users', 'user_groups', "
                "'image_model_user_access', 'image_model_group_access')"
            )
        ).mappings().all()
        table_engines = {str(row["TABLE_NAME"]): row["ENGINE"] for row in table_rows}

        missing_specs = [spec for spec in _MYSQL_IMAGE_MODEL_ACCESS_SPECS if spec[0] not in table_engines]
        required_parents = {"ai_image_models"}
        required_parents.update(spec[2] for spec in missing_specs)
        if not missing_specs or not required_parents.issubset(table_engines):
            return

        for parent_table in sorted(required_parents):
            parent_engine = str(table_engines[parent_table] or "")
            if parent_engine.lower() == "innodb":
                continue
            connection.execute(text(f"ALTER TABLE `{parent_table}` ENGINE=InnoDB"))

        column_rows = connection.execute(
            text(
                "SELECT TABLE_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = 'id' "
                "AND TABLE_NAME IN ('ai_image_models', 'users', 'user_groups')"
            )
        ).mappings().all()
        id_types = {str(row["TABLE_NAME"]): str(row["COLUMN_TYPE"]) for row in column_rows}

        for table_name, related_column_name, related_table_name in missing_specs:
            model_id_type = id_types.get("ai_image_models")
            related_id_type = id_types.get(related_table_name)
            if not model_id_type or not related_id_type:
                continue
            connection.execute(
                text(
                    _mysql_image_model_access_create_sql(
                        table_name,
                        related_column_name,
                        related_table_name,
                        model_id_type,
                        related_id_type,
                    )
                )
            )


def _legacy_snapshot_prefix_hash(rows: list[dict]) -> str:
    def canonical_kind(value: object) -> str:
        # SQLAlchemy's Enum storage uses member names (``USER``) on some
        # existing SQLite/MySQL deployments, while the live compiler hashes
        # ContextEventKind.value (``user``).  Normalize here so a genuinely
        # unchanged historical prefix remains reusable after migration.
        return str(value or "").rsplit(".", 1)[-1].lower()

    payload = [
        {
            "id": int(row["id"]),
            "message_id": int(row["message_id"]) if row["message_id"] is not None else None,
            "kind": canonical_kind(row["kind"]),
            "payload": json.loads(row["payload_json"] or "{}"),
            "document_revision": str(row["document_revision"] or ""),
            "legacy": bool(row["is_legacy"]),
        }
        for row in rows
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _answered_user_question_presentation(answer: dict | None) -> tuple[str, dict]:
    action = str((answer or {}).get("action") or "")
    if action == "no_response":
        return (
            "用户在规定时间内未回复，已自动跳过本次确认并继续处理排版。",
            {"kind": "question", "summary": "用户未回复，已自动继续"},
        )
    if action == "skipped":
        return (
            "用户跳过了本次确认，继续处理排版。",
            {"kind": "question", "summary": "用户已跳过确认"},
        )
    return "已收到用户回答，继续处理排版。", {"kind": "question", "summary": "已收到用户回答"}


def _answered_user_question_tool(tool_call_id: str, answer: dict | None = None) -> dict:
    result, activity = _answered_user_question_presentation(answer)
    return {
        "id": tool_call_id,
        "name": "ask_user",
        "arguments": {},
        "status": "success",
        "preparing": False,
        "result": result,
        "html_changed": False,
        "activity": activity,
        "read_range": None,
        "change_summary": None,
    }


def _is_timed_out_question_retry(tool: dict) -> bool:
    return (
        tool.get("name") == "ask_user"
        and "用户已在本轮提问中超时未回复" in str(tool.get("result") or "")
    )


def _repair_answered_user_question_timeline(
    tool_calls: list[dict],
    turn_blocks: list[dict],
    answered_tool_call_ids: list[str],
    answers_by_tool_call_id: dict[str, dict] | None = None,
) -> bool:
    """Repair timelines written before ask_user exposed stable provider IDs."""
    expected_ids = list(dict.fromkeys(item for item in answered_tool_call_ids if item))
    if not expected_ids:
        return False
    present_ids = {
        str(block["tool"].get("id") or "")
        for block in turn_blocks
        if isinstance(block, dict)
        and isinstance(block.get("tool"), dict)
        and block["tool"].get("name") == "ask_user"
    }
    answers_by_tool_call_id = answers_by_tool_call_id or {}
    if set(expected_ids).issubset(present_ids):
        changed = False
        all_tools = [
            *[item for item in tool_calls if isinstance(item, dict)],
            *[
                block.get("tool")
                for block in turn_blocks
                if isinstance(block, dict) and isinstance(block.get("tool"), dict)
            ],
        ]
        for tool in all_tools:
            tool_call_id = str(tool.get("id") or "")
            if tool_call_id not in expected_ids or tool.get("name") != "ask_user":
                continue
            result, activity = _answered_user_question_presentation(answers_by_tool_call_id.get(tool_call_id))
            if (
                tool.get("status") != "success"
                or tool.get("preparing") is not False
                or tool.get("result") != result
                or tool.get("activity") != activity
            ):
                tool["status"] = "success"
                tool["preparing"] = False
                tool["result"] = result
                tool["activity"] = activity
                changed = True
        if any(
            str(answer.get("action") or "") == "no_response"
            for answer in answers_by_tool_call_id.values()
        ):
            retry_result = "用户未回复，已自动跳过本次确认，继续处理排版。"
            retry_activity = {
                "kind": "question",
                "summary": "用户未回复，已自动继续",
                "details": {"reason": "user_question_timed_out", "recoverable": True},
            }
            for tool in all_tools:
                if not _is_timed_out_question_retry(tool):
                    continue
                tool["status"] = "success"
                tool["preparing"] = False
                tool["result"] = retry_result
                tool["activity"] = retry_activity
                changed = True
        return changed

    first_question_index = next(
        (
            index
            for index, block in enumerate(turn_blocks)
            if isinstance(block, dict)
            and isinstance(block.get("tool"), dict)
            and block["tool"].get("name") == "ask_user"
        ),
        len(turn_blocks),
    )
    retained_before_questions = sum(
        1
        for block in turn_blocks[:first_question_index]
        if not (
            isinstance(block, dict)
            and isinstance(block.get("tool"), dict)
            and block["tool"].get("name") == "ask_user"
        )
    )
    retained_blocks = [
        block
        for block in turn_blocks
        if not (
            isinstance(block, dict)
            and isinstance(block.get("tool"), dict)
            and block["tool"].get("name") == "ask_user"
        )
    ]
    question_tools = [
        _answered_user_question_tool(tool_call_id, answers_by_tool_call_id.get(tool_call_id))
        for tool_call_id in expected_ids
    ]
    question_blocks = [
        {"id": f"block-{tool_call_id}", "type": "tool", "state": "done", "content": "", "tool": tool}
        for tool_call_id, tool in zip(expected_ids, question_tools)
    ]
    turn_blocks[:] = (
        retained_blocks[:retained_before_questions]
        + question_blocks
        + retained_blocks[retained_before_questions:]
    )
    tool_calls[:] = question_tools + [
        tool for tool in tool_calls if not (isinstance(tool, dict) and tool.get("name") == "ask_user")
    ]
    return True


def migrate_schema() -> None:
    """补齐已发布数据库缺少的轻量字段。

    当前项目未引入 Alembic；新部署由 ``Base.metadata.create_all`` 创建完整结构，
    此处覆盖已有 SQLite/MySQL 库的向前兼容升级路径。
    """
    # Fresh application startup creates every table before this function. Keep
    # this explicit for standalone compatibility migrations and repair tools.
    ArticleTypographySettings.__table__.create(bind=engine, checkfirst=True)
    is_sqlite = engine.url.drivername.startswith("sqlite")
    with engine.begin() as connection:
        # Bind the inspector to the active migration connection. On SQLite,
        # an engine-bound inspector may borrow the same DB-API connection via
        # the pool and roll back the migration transaction when its temporary
        # connection is closed.
        inspector = inspect(connection)
        # Both the run-admission gate and the SQLite fallback migration lock
        # need deterministic rows before application requests are accepted.
        lock_insert = "INSERT OR IGNORE" if is_sqlite else "INSERT IGNORE"
        connection.execute(text(f"{lock_insert} INTO app_runtime_locks (name) VALUES ('agent-admission')"))
        if inspector.has_table("operation_logs"):
            operation_log_columns = {column["name"] for column in inspector.get_columns("operation_logs")}
            for column_name, definition in {
                "client_ip": "VARCHAR(45) NOT NULL DEFAULT ''",
                "user_agent": "VARCHAR(512) NOT NULL DEFAULT ''",
            }.items():
                if column_name not in operation_log_columns:
                    connection.execute(text(f"ALTER TABLE operation_logs ADD COLUMN {column_name} {definition}"))
            operation_log_indexes = {index["name"] for index in inspector.get_indexes("operation_logs")}
            if "ix_operation_logs_client_ip_created" not in operation_log_indexes:
                connection.execute(text("CREATE INDEX ix_operation_logs_client_ip_created ON operation_logs (client_ip, created_at)"))
        if inspector.has_table("agent_runs"):
            agent_run_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
            for column_name, definition in {
                "origin_client_ip": "VARCHAR(45) NOT NULL DEFAULT ''",
                "origin_user_agent": "VARCHAR(512) NOT NULL DEFAULT ''",
            }.items():
                if column_name not in agent_run_columns:
                    connection.execute(text(f"ALTER TABLE agent_runs ADD COLUMN {column_name} {definition}"))
        if inspector.has_table("storage_configs"):
            storage_columns = {column["name"] for column in inspector.get_columns("storage_configs")}
            storage_column_definitions = (
                {
                    "provider": "VARCHAR(32) NOT NULL DEFAULT 'aliyun_oss'",
                    "region_or_zone": "VARCHAR(128) NOT NULL DEFAULT ''",
                    "upload_endpoint": "VARCHAR(256) NOT NULL DEFAULT ''",
                }
                if is_sqlite
                else {
                    "provider": "VARCHAR(32) NOT NULL DEFAULT 'aliyun_oss'",
                    "region_or_zone": "VARCHAR(128) NOT NULL DEFAULT ''",
                    "upload_endpoint": "VARCHAR(256) NOT NULL DEFAULT ''",
                }
            )
            for column_name, definition in storage_column_definitions.items():
                if column_name not in storage_columns:
                    connection.execute(text(f"ALTER TABLE storage_configs ADD COLUMN {column_name} {definition}"))
            connection.execute(
                text("UPDATE storage_configs SET provider = 'aliyun_oss' WHERE provider IS NULL OR TRIM(provider) = ''")
            )
        if inspector.has_table("image_generations"):
            image_generation_columns = {column["name"] for column in inspector.get_columns("image_generations")}
            for column_name, definition in {
                "operation": "VARCHAR(16) NOT NULL DEFAULT 'generate'",
                "source_image_url": "VARCHAR(4096) NOT NULL DEFAULT ''",
                "source_image_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
                "source_asset_url": "VARCHAR(4096) NOT NULL DEFAULT ''",
                "source_object_key": "VARCHAR(512) NOT NULL DEFAULT ''",
                "source_storage_mode": "VARCHAR(12) NOT NULL DEFAULT ''",
                "target_image_index": "INTEGER NOT NULL DEFAULT -1",
                "timeout_seconds": "INTEGER NOT NULL DEFAULT 180",
            }.items():
                if column_name not in image_generation_columns:
                    connection.execute(text(f"ALTER TABLE image_generations ADD COLUMN {column_name} {definition}"))
        if inspector.has_table("image_library_assets"):
            image_library_columns = {column["name"] for column in inspector.get_columns("image_library_assets")}
            for column_name, definition in {
                "is_shared": "BOOLEAN NOT NULL DEFAULT 0",
                "deleted_at": "DATETIME NULL",
                "updated_at": "DATETIME NULL",
            }.items():
                if column_name not in image_library_columns:
                    connection.execute(text(f"ALTER TABLE image_library_assets ADD COLUMN {column_name} {definition}"))
            connection.execute(
                text("UPDATE image_library_assets SET updated_at = created_at WHERE updated_at IS NULL")
            )
            if not is_sqlite:
                updated_at_definition = connection.execute(
                    text(
                        "SELECT IS_NULLABLE, COLUMN_DEFAULT, EXTRA FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'image_library_assets' "
                        "AND COLUMN_NAME = 'updated_at'"
                    )
                ).mappings().one()
                has_current_timestamp_default = "current_timestamp" in str(
                    updated_at_definition["COLUMN_DEFAULT"] or ""
                ).lower()
                has_on_update = "on update current_timestamp" in str(
                    updated_at_definition["EXTRA"] or ""
                ).lower()
                if (
                    updated_at_definition["IS_NULLABLE"] != "NO"
                    or not has_current_timestamp_default
                    or not has_on_update
                ):
                    connection.execute(
                        text(
                            "ALTER TABLE image_library_assets MODIFY COLUMN updated_at "
                            "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
                        )
                    )
            image_library_indexes = {index["name"] for index in inspector.get_indexes("image_library_assets")}
            for index_name, columns in {
                "ix_image_library_assets_is_shared": "is_shared",
                "ix_image_library_assets_deleted_at": "deleted_at",
            }.items():
                if index_name not in image_library_indexes:
                    connection.execute(text(f"CREATE INDEX {index_name} ON image_library_assets ({columns})"))
        if inspector.has_table("image_library_settings"):
            settings_insert = "INSERT OR IGNORE" if is_sqlite else "INSERT IGNORE"
            connection.execute(
                text(f"{settings_insert} INTO image_library_settings (id, mode) VALUES (1, 'personal')")
            )
        settings_insert = "INSERT OR IGNORE" if is_sqlite else "INSERT IGNORE"
        connection.execute(
            text(
                f"{settings_insert} INTO article_typography_settings "
                "(id, horizontal_padding_px, paragraph_spacing_px, font_size_px, "
                "line_height_em, letter_spacing_px, text_indent_em, text_color) "
                "VALUES (1, 4, 20, 15, 2, 1, 2, '#000000')"
            )
        )
        if inspector.has_table("ai_image_models"):
            image_model_columns = {column["name"] for column in inspector.get_columns("ai_image_models")}
            if "deleted_at" not in image_model_columns:
                connection.execute(text("ALTER TABLE ai_image_models ADD COLUMN deleted_at DATETIME NULL"))
            if "is_enabled" not in image_model_columns:
                connection.execute(text("ALTER TABLE ai_image_models ADD COLUMN is_enabled BOOLEAN NOT NULL DEFAULT 1"))
            if "availability_time_ranges" not in image_model_columns:
                if is_sqlite:
                    connection.execute(
                        text("ALTER TABLE ai_image_models ADD COLUMN availability_time_ranges JSON NOT NULL DEFAULT '[]'")
                    )
                else:
                    connection.execute(text("ALTER TABLE ai_image_models ADD COLUMN availability_time_ranges JSON NULL"))
                    connection.execute(text("UPDATE ai_image_models SET availability_time_ranges = JSON_ARRAY() WHERE availability_time_ranges IS NULL"))
                    connection.execute(text("ALTER TABLE ai_image_models MODIFY COLUMN availability_time_ranges JSON NOT NULL"))
            image_model_indexes = {index["name"] for index in inspector.get_indexes("ai_image_models")}
            if "ix_ai_image_models_deleted_at" not in image_model_indexes:
                connection.execute(text("CREATE INDEX ix_ai_image_models_deleted_at ON ai_image_models (deleted_at)"))
        # SQLAlchemy stores DocumentSourceType member names in native MySQL ENUM
        # columns. Existing deployments need this explicit expansion before a
        # newer import source can be persisted.
        if not is_sqlite:
            enum_values = ("BLANK", "PDF", "WORD", "MARKDOWN", "WEB")
            enum_definition = ", ".join(f"'{value}'" for value in enum_values)
            if inspector.has_table("documents"):
                document_columns = {column["name"]: column for column in inspector.get_columns("documents")}
                source_type_column = document_columns.get("source_type")
                existing_values = set(getattr(source_type_column["type"], "enums", ()) if source_type_column else ())
                if not set(enum_values).issubset(existing_values):
                    connection.execute(
                        text(
                            "ALTER TABLE documents MODIFY COLUMN source_type "
                            f"ENUM({enum_definition}) NOT NULL DEFAULT 'BLANK'"
                        )
                    )
        if inspector.has_table("ai_providers"):
            provider_columns = {column["name"]: column for column in inspector.get_columns("ai_providers")}
            for column_name, definition in {
                "image_protocol": "VARCHAR(48) NOT NULL DEFAULT ''",
                "image_base_url": "VARCHAR(512) NOT NULL DEFAULT ''",
                "is_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            }.items():
                if column_name not in provider_columns:
                    connection.execute(text(f"ALTER TABLE ai_providers ADD COLUMN {column_name} {definition}"))
            if "availability_time_ranges" not in provider_columns:
                if is_sqlite:
                    connection.execute(
                        text("ALTER TABLE ai_providers ADD COLUMN availability_time_ranges JSON NOT NULL DEFAULT '[]'")
                    )
                else:
                    connection.execute(text("ALTER TABLE ai_providers ADD COLUMN availability_time_ranges JSON NULL"))
                    connection.execute(text("UPDATE ai_providers SET availability_time_ranges = JSON_ARRAY() WHERE availability_time_ranges IS NULL"))
                    connection.execute(text("ALTER TABLE ai_providers MODIFY COLUMN availability_time_ranges JSON NOT NULL"))
            if not is_sqlite:
                provider_type_column = provider_columns.get("provider_type")
                provider_enum_values = ("OPENAI_COMPATIBLE", "OPENAI_RESPONSES", "ANTHROPIC", "GEMINI_NATIVE")
                existing_provider_values = set(
                    getattr(provider_type_column["type"], "enums", ()) if provider_type_column else ()
                )
                if not set(provider_enum_values).issubset(existing_provider_values):
                    provider_enum_definition = ", ".join(f"'{value}'" for value in provider_enum_values)
                    connection.execute(
                        text(
                            "ALTER TABLE ai_providers MODIFY COLUMN provider_type "
                            f"ENUM({provider_enum_definition}) NOT NULL"
                        )
                    )
            if inspector.has_table("chat_sessions"):
                chat_session_columns = {column["name"] for column in inspector.get_columns("chat_sessions")}
                for column_name, definition in {
                    "image_model_id": "BIGINT NULL",
                }.items():
                    if column_name not in chat_session_columns:
                        connection.execute(text(f"ALTER TABLE chat_sessions ADD COLUMN {column_name} {definition}"))
            if not is_sqlite and inspector.has_table("document_imports"):
                import_columns = {column["name"]: column for column in inspector.get_columns("document_imports")}
                source_type_column = import_columns.get("source_type")
                existing_values = set(getattr(source_type_column["type"], "enums", ()) if source_type_column else ())
                if not set(enum_values).issubset(existing_values):
                    connection.execute(
                        text(
                            "ALTER TABLE document_imports MODIFY COLUMN source_type "
                            f"ENUM({enum_definition}) NOT NULL"
                        )
                    )
        if inspector.has_table("layout_capture_sessions"):
            capture_session_columns = {
                column["name"] for column in inspector.get_columns("layout_capture_sessions")
            }
            if "purpose" not in capture_session_columns:
                connection.execute(
                    text(
                        "ALTER TABLE layout_capture_sessions ADD COLUMN "
                        "purpose VARCHAR(32) NOT NULL DEFAULT 'layout_reference'"
                    )
                )
        if inspector.has_table("web_article_imports"):
            web_import_columns = {column["name"] for column in inspector.get_columns("web_article_imports")}
            web_import_definitions = {
                "cover_asset_id": "VARCHAR(32) NULL",
                "cover_requires_crops": "BOOLEAN NOT NULL DEFAULT 0",
            }
            for column_name, definition in web_import_definitions.items():
                if column_name not in web_import_columns:
                    connection.execute(text(f"ALTER TABLE web_article_imports ADD COLUMN {column_name} {definition}"))
        if inspector.has_table("web_article_import_assets"):
            web_import_asset_columns = {
                column["name"] for column in inspector.get_columns("web_article_import_assets")
            }
            for column_name in ("width", "height"):
                if column_name not in web_import_asset_columns:
                    connection.execute(
                        text(f"ALTER TABLE web_article_import_assets ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT 0")
                    )
        # Refresh after the provider-table DDL above. Some legacy-schema tests
        # deliberately replace ai_models after the initial inspector snapshot.
        # Use the active migration connection: SQLAlchemy Inspector can retain
        # a stale table-info cache when a table was replaced on SQLite.
        if is_sqlite:
            model_columns = {
                str(row[1])
                for row in connection.exec_driver_sql("PRAGMA table_info(ai_models)").fetchall()
            }
        else:
            model_columns = {
                str(row[0])
                for row in connection.exec_driver_sql("SHOW COLUMNS FROM ai_models").fetchall()
            }
        if "thinking_config" not in model_columns:
            if is_sqlite:
                connection.execute(
                    text("ALTER TABLE ai_models ADD COLUMN thinking_config JSON NOT NULL DEFAULT '{}'")
                )
            else:
                # MySQL 5.7 不支持 JSON 列默认值；新增后回填即可。
                connection.execute(text("ALTER TABLE ai_models ADD COLUMN thinking_config JSON NULL"))
                connection.execute(text("UPDATE ai_models SET thinking_config = '{}' WHERE thinking_config IS NULL"))
        if "description" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN description VARCHAR(1024) NOT NULL DEFAULT ''")
            )
        if "context_window_tokens" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN context_window_tokens INT NOT NULL DEFAULT 32768")
            )
        if "context_compaction_threshold_tokens" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN context_compaction_threshold_tokens INT NOT NULL DEFAULT 24576")
            )
        if "max_output_tokens" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN max_output_tokens INT NOT NULL DEFAULT 8192")
            )
        if "tool_result_max_tokens" not in model_columns:
            connection.execute(
                text(
                    "ALTER TABLE ai_models ADD COLUMN tool_result_max_tokens INT NOT NULL "
                    f"DEFAULT {DEFAULT_TOOL_RESULT_MAX_TOKENS}"
                )
            )
        preview_budget_migrated = connection.execute(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": TOOL_PREVIEW_BUDGET_MIGRATION},
        ).scalar()
        if preview_budget_migrated is None:
            # Only upgrade the complete old conservative tuple. A model with
            # any adjusted budget remains an administrator-owned setting.
            connection.execute(
                text(
                    "UPDATE ai_models SET tool_result_max_tokens = :new_limit "
                    "WHERE context_window_tokens = 32768 "
                    "AND context_compaction_threshold_tokens = 24576 "
                    "AND max_output_tokens = 8192 "
                    "AND tool_result_max_tokens = 8192"
                ),
                {"new_limit": DEFAULT_TOOL_RESULT_MAX_TOKENS},
            )
            connection.execute(
                text(f"{lock_insert} INTO schema_migrations (version) VALUES (:version)"),
                {"version": TOOL_PREVIEW_BUDGET_MIGRATION},
            )
        if "access_mode" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN access_mode VARCHAR(16) NOT NULL DEFAULT 'all'")
            )
        if "is_multimodal" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN is_multimodal BOOLEAN NOT NULL DEFAULT 0")
            )
        if "supports_disabled_thinking" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN supports_disabled_thinking BOOLEAN NOT NULL DEFAULT 1")
            )
        if "default_thinking_effort" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN default_thinking_effort VARCHAR(16) NOT NULL DEFAULT 'auto'")
            )
        if "prompt_cache_enabled" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN prompt_cache_enabled BOOLEAN NOT NULL DEFAULT 0")
            )
        if "is_enabled" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN is_enabled BOOLEAN NOT NULL DEFAULT 1")
            )
        if "availability_time_ranges" not in model_columns:
            if is_sqlite:
                connection.execute(
                    text("ALTER TABLE ai_models ADD COLUMN availability_time_ranges JSON NOT NULL DEFAULT '[]'")
                )
            else:
                connection.execute(text("ALTER TABLE ai_models ADD COLUMN availability_time_ranges JSON NULL"))
                connection.execute(text("UPDATE ai_models SET availability_time_ranges = JSON_ARRAY() WHERE availability_time_ranges IS NULL"))
                connection.execute(text("ALTER TABLE ai_models MODIFY COLUMN availability_time_ranges JSON NOT NULL"))

        # Custom themes originally stored their complete library directly on
        # ``gzh_themes``.  Keep those columns as a compatibility mirror and
        # materialize every existing record as an immutable v1 revision.
        if inspector.has_table("gzh_themes"):
            theme_columns = {column["name"] for column in inspector.get_columns("gzh_themes")}
            if "active_version_id" not in theme_columns:
                version_id_type = "INTEGER" if is_sqlite else "BIGINT UNSIGNED NULL"
                connection.execute(text(f"ALTER TABLE gzh_themes ADD COLUMN active_version_id {version_id_type}"))
            if inspector.has_table("gzh_theme_versions"):
                connection.execute(
                    text(
                        "INSERT INTO gzh_theme_versions "
                        "(theme_id, version, generation_brief, source_markdown, preview_html, manifest_json, validation_json, status, created_by_id, created_at, published_at) "
                        "SELECT t.id, 1, '', t.source_markdown, t.preview_html, '{}', '[]', "
                        "CASE WHEN t.status = 'published' THEN 'published' WHEN t.status = 'archived' THEN 'archived' ELSE 'draft' END, "
                        "t.created_by_id, t.created_at, CASE WHEN t.status = 'published' THEN t.updated_at ELSE NULL END "
                        "FROM gzh_themes t "
                        "WHERE NOT EXISTS (SELECT 1 FROM gzh_theme_versions v WHERE v.theme_id = t.id)"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE gzh_themes SET active_version_id = "
                        "(SELECT v.id FROM gzh_theme_versions v WHERE v.theme_id = gzh_themes.id AND v.version = 1) "
                        "WHERE active_version_id IS NULL"
                    )
                )

        # Theme generation is a multi-stage job. Persist its current phase so
        # a polling browser can show meaningful progress after any worker swap.
        if inspector.has_table("gzh_theme_generations"):
            generation_columns = {
                column["name"] for column in inspector.get_columns("gzh_theme_generations")
            }
            generation_definitions = {
                "progress_stage": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
                "progress_current": "INTEGER NOT NULL DEFAULT 0",
                "progress_total": "INTEGER NOT NULL DEFAULT 0",
                "progress_message": "VARCHAR(256) NOT NULL DEFAULT ''",
            }
            for column_name, definition in generation_definitions.items():
                if column_name not in generation_columns:
                    connection.execute(
                        text(f"ALTER TABLE gzh_theme_generations ADD COLUMN {column_name} {definition}")
                    )

        # Layout-reference bindings predate the selectable imitation level.
        # Keep existing sessions on the former structural behavior.
        if inspector.has_table("chat_session_layout_references"):
            layout_reference_columns = {
                column["name"] for column in inspector.get_columns("chat_session_layout_references")
            }
            if "imitation_strength" not in layout_reference_columns:
                connection.execute(
                    text(
                        "ALTER TABLE chat_session_layout_references "
                        "ADD COLUMN imitation_strength VARCHAR(16) NOT NULL DEFAULT 'structure'"
                    )
                )

        if inspector.has_table("wechat_drafts"):
            wechat_draft_columns = {column["name"]: column for column in inspector.get_columns("wechat_drafts")}
            if "sync_mode" not in wechat_draft_columns:
                connection.execute(
                    text("ALTER TABLE wechat_drafts ADD COLUMN sync_mode VARCHAR(16) NOT NULL DEFAULT 'create'")
                )
            if not is_sqlite:
                article_title_column = wechat_draft_columns.get("article_title")
                current_length = getattr(article_title_column["type"], "length", None) if article_title_column else None
                if current_length is not None and current_length < 64:
                    connection.execute(text("ALTER TABLE wechat_drafts MODIFY COLUMN article_title VARCHAR(64) NOT NULL DEFAULT ''"))

        # Theme proposals used to snapshot only the raw Markdown library.  Add
        # the derived recipe/component selection so an approval remains
        # reproducible after a vendor-theme update.
        if inspector.has_table("gzh_theme_proposals"):
            proposal_columns = {column["name"] for column in inspector.get_columns("gzh_theme_proposals")}
            proposal_definitions = (
                {
                    "theme_manifest_json": "TEXT NOT NULL DEFAULT ''",
                    "theme_manifest_checksum": "VARCHAR(64) NOT NULL DEFAULT ''",
                    "article_type": "VARCHAR(128) NOT NULL DEFAULT ''",
                    "recipe_id": "VARCHAR(128) NOT NULL DEFAULT ''",
                    "selected_component_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                }
                if is_sqlite
                else {
                    "theme_manifest_json": "LONGTEXT NULL",
                    "theme_manifest_checksum": "VARCHAR(64) NOT NULL DEFAULT ''",
                    "article_type": "VARCHAR(128) NOT NULL DEFAULT ''",
                    "recipe_id": "VARCHAR(128) NOT NULL DEFAULT ''",
                    "selected_component_ids_json": "LONGTEXT NULL",
                }
            )
            for column_name, definition in proposal_definitions.items():
                if column_name not in proposal_columns:
                    connection.execute(text(f"ALTER TABLE gzh_theme_proposals ADD COLUMN {column_name} {definition}"))
            if not is_sqlite:
                connection.execute(
                    text("UPDATE gzh_theme_proposals SET theme_manifest_json = '' WHERE theme_manifest_json IS NULL")
                )
                connection.execute(
                    text("UPDATE gzh_theme_proposals SET selected_component_ids_json = '[]' WHERE selected_component_ids_json IS NULL")
                )

        # Theme selection now belongs to a conversation, rather than being
        # inferred from the document's newest applied theme.  Preserve the
        # useful existing choice for old sessions once, without guessing from
        # historical per-message component attachments.
        if inspector.has_table("chat_session_theme_contexts") and inspector.has_table("gzh_theme_proposals"):
            bound_session_ids = set(
                connection.execute(text("SELECT session_id FROM chat_session_theme_contexts")).scalars().all()
            )
            session_ids = connection.execute(text("SELECT id FROM chat_sessions")).scalars().all()
            theme_context_rows = []
            for session_id in session_ids:
                if int(session_id) in bound_session_ids:
                    continue
                proposal_id = connection.execute(
                    text(
                        "SELECT id FROM gzh_theme_proposals "
                        "WHERE session_id = :session_id AND UPPER(status) IN ('APPROVED', 'APPLIED') "
                        "ORDER BY applied_at DESC, created_at DESC, id DESC LIMIT 1"
                    ),
                    {"session_id": session_id},
                ).scalar()
                if proposal_id:
                    theme_context_rows.append(
                        {"session_id": int(session_id), "gzh_theme_proposal_id": str(proposal_id)}
                    )
            if theme_context_rows:
                connection.execute(
                    text(
                        f"{lock_insert} INTO chat_session_theme_contexts "
                        "(session_id, gzh_theme_proposal_id) VALUES (:session_id, :gzh_theme_proposal_id)"
                    ),
                    theme_context_rows,
                )
        message_columns = {column["name"] for column in inspector.get_columns("chat_messages")}
        if "template_refs_json" not in message_columns:
            template_refs_column = "TEXT NOT NULL DEFAULT '[]'" if is_sqlite else "LONGTEXT NULL"
            connection.execute(text(f"ALTER TABLE chat_messages ADD COLUMN template_refs_json {template_refs_column}"))
            if not is_sqlite:
                connection.execute(text("UPDATE chat_messages SET template_refs_json = '[]' WHERE template_refs_json IS NULL"))
        if "reasoning_trace_json" not in message_columns:
            if is_sqlite:
                connection.execute(
                    text("ALTER TABLE chat_messages ADD COLUMN reasoning_trace_json TEXT NOT NULL DEFAULT '{}'")
                )
            else:
                # 旧版 MySQL 同样不允许 TEXT 默认值。
                connection.execute(text("ALTER TABLE chat_messages ADD COLUMN reasoning_trace_json LONGTEXT NULL"))
                connection.execute(
                    text("UPDATE chat_messages SET reasoning_trace_json = '{}' WHERE reasoning_trace_json IS NULL")
                )
        message_column_definitions = (
            {
                "html_before": "TEXT NULL",
                "html_after": "TEXT NULL",
                "is_superseded": "BOOLEAN NOT NULL DEFAULT 0",
                "superseded_at": "DATETIME NULL",
                "selected_elements_json": "TEXT NOT NULL DEFAULT '[]'",
                "turn_blocks_json": "TEXT NOT NULL DEFAULT '[]'",
                "history_archive_id": "INTEGER NULL",
                "created_by_id": "INTEGER NULL",
                "gzh_theme_proposal_id": "VARCHAR(36) NULL",
            }
            if is_sqlite
            else {
                "html_before": "LONGTEXT NULL",
                "html_after": "LONGTEXT NULL",
                "is_superseded": "TINYINT(1) NOT NULL DEFAULT 0",
                "superseded_at": "DATETIME NULL",
                "selected_elements_json": "LONGTEXT NULL",
                "turn_blocks_json": "LONGTEXT NULL",
                "history_archive_id": "BIGINT UNSIGNED NULL",
                "created_by_id": "BIGINT UNSIGNED NULL",
                "gzh_theme_proposal_id": "VARCHAR(36) NULL",
            }
        )
        for column_name, definition in message_column_definitions.items():
            if column_name not in message_columns:
                connection.execute(text(f"ALTER TABLE chat_messages ADD COLUMN {column_name} {definition}"))
        message_indexes = {index["name"] for index in inspect(connection).get_indexes("chat_messages")}
        if "ix_chat_messages_history_archive_id" not in message_indexes:
            connection.execute(text("CREATE INDEX ix_chat_messages_history_archive_id ON chat_messages (history_archive_id)"))
        if "ix_chat_messages_created_by_id" not in message_indexes:
            connection.execute(text("CREATE INDEX ix_chat_messages_created_by_id ON chat_messages (created_by_id)"))
        if "ix_chat_messages_gzh_theme_proposal_id" not in message_indexes:
            connection.execute(
                text("CREATE INDEX ix_chat_messages_gzh_theme_proposal_id ON chat_messages (gzh_theme_proposal_id)")
            )
        if "selected_elements_json" not in message_columns and not is_sqlite:
            connection.execute(
                text("UPDATE chat_messages SET selected_elements_json = '[]' WHERE selected_elements_json IS NULL")
            )
        if "turn_blocks_json" not in message_columns and not is_sqlite:
            connection.execute(
                text("UPDATE chat_messages SET turn_blocks_json = '[]' WHERE turn_blocks_json IS NULL")
            )
        # Existing superseded rows predate the timestamped invalidation rule.
        # Their original creation time is the only safe monotonic lower bound,
        # and prevents them from invalidating snapshots created later.
        if "superseded_at" not in message_columns:
            connection.execute(
                text(
                    "UPDATE chat_messages SET superseded_at = created_at "
                    "WHERE is_superseded = 1 AND superseded_at IS NULL"
                )
            )

        if inspector.has_table("chat_context_snapshots"):
            snapshot_columns = {column["name"] for column in inspect(connection).get_columns("chat_context_snapshots")}
            if "invalidation_reason" not in snapshot_columns:
                connection.execute(
                    text("ALTER TABLE chat_context_snapshots ADD COLUMN invalidation_reason VARCHAR(32) NOT NULL DEFAULT ''")
                )
            snapshot_definitions = {
                "source_event_count": "INTEGER NOT NULL DEFAULT 0",
                "source_prefix_hash": "VARCHAR(80) NOT NULL DEFAULT ''",
                "context_generation": "INTEGER NOT NULL DEFAULT 0",
                # Only the active row holds ``1``.  A unique index on this
                # nullable column enforces one active snapshot per session on
                # both SQLite and MySQL without constraining history rows.
                "active_slot": "INTEGER NULL",
            }
            for column_name, definition in snapshot_definitions.items():
                if column_name not in snapshot_columns:
                    connection.execute(text(f"ALTER TABLE chat_context_snapshots ADD COLUMN {column_name} {definition}"))

        # Chat sessions were introduced after document-level chat history.
        # Backfill a single initial session for every existing document before
        # attaching old messages, runs, and compacted memory to it.
        session_rows = connection.execute(text("SELECT id, document_id FROM chat_sessions")).mappings().all()
        session_by_document = {int(row["document_id"]): int(row["id"]) for row in session_rows}
        document_ids = connection.execute(text("SELECT id FROM documents")).scalars().all()
        missing_session_documents = [int(document_id) for document_id in document_ids if int(document_id) not in session_by_document]
        if missing_session_documents:
            connection.execute(
                ChatSession.__table__.insert(),
                [{"document_id": document_id, "title": "初始对话", "is_archived": False, "context_start_message_id": 0} for document_id in missing_session_documents],
            )
            session_rows = connection.execute(text("SELECT id, document_id FROM chat_sessions")).mappings().all()
            session_by_document = {int(row["document_id"]): int(row["id"]) for row in session_rows}

        session_columns = {column["name"] for column in inspect(connection).get_columns("chat_sessions")}
        if "context_generation" not in session_columns:
            connection.execute(text("ALTER TABLE chat_sessions ADD COLUMN context_generation INTEGER NOT NULL DEFAULT 0"))

        message_columns = {column["name"] for column in inspect(connection).get_columns("chat_messages")}
        if "session_id" not in message_columns:
            session_column = "INTEGER" if is_sqlite else "BIGINT UNSIGNED NULL"
            connection.execute(text(f"ALTER TABLE chat_messages ADD COLUMN session_id {session_column}"))
        for document_id, session_id in session_by_document.items():
            connection.execute(
                text("UPDATE chat_messages SET session_id = :session_id WHERE document_id = :document_id AND session_id IS NULL"),
                {"session_id": session_id, "document_id": document_id},
            )
        message_indexes = {index["name"] for index in inspect(connection).get_indexes("chat_messages")}
        if "ix_chat_messages_session_id" not in message_indexes:
            connection.execute(text("CREATE INDEX ix_chat_messages_session_id ON chat_messages (session_id)"))

        memory_columns = {column["name"] for column in inspect(connection).get_columns("chat_session_memories")}
        if "compacted_through_event_id" not in memory_columns:
            connection.execute(
                text("ALTER TABLE chat_session_memories ADD COLUMN compacted_through_event_id INTEGER NOT NULL DEFAULT 0")
            )
        if "compaction_strategy" not in memory_columns:
            strategy_type = "VARCHAR(32) NOT NULL DEFAULT ''" if is_sqlite else "VARCHAR(32) NOT NULL DEFAULT ''"
            connection.execute(text(f"ALTER TABLE chat_session_memories ADD COLUMN compaction_strategy {strategy_type}"))

        # Full oversized tool output is deliberately time-bounded.  Existing
        # session-retained rows retain their existing expiry timestamp but are
        # converted to TTL rows so historical output cannot grow without end.
        if inspector.has_table("chat_tool_outputs"):
            output_columns = {column["name"] for column in inspect(connection).get_columns("chat_tool_outputs")}
            if "retention_mode" not in output_columns:
                definition = "VARCHAR(16) NOT NULL DEFAULT 'ttl'"
                connection.execute(text(f"ALTER TABLE chat_tool_outputs ADD COLUMN retention_mode {definition}"))
            connection.execute(
                text("UPDATE chat_tool_outputs SET retention_mode = 'ttl' WHERE retention_mode IS NULL OR retention_mode = '' OR retention_mode = 'session'")
            )

        # ``create_all`` creates this table for fresh deployments. Existing
        # memory rows are mirrored once so a new context compiler can use an
        # immutable snapshot without losing a previously generated summary.
        if inspector.has_table("chat_context_snapshots") and inspector.has_table("chat_session_memories"):
            existing_snapshot_sessions = set(connection.execute(text("SELECT DISTINCT session_id FROM chat_context_snapshots")).scalars().all())
            legacy_snapshot_rows = connection.execute(
                text(
                    "SELECT session_id, compacted_through_message_id, compacted_through_event_id, "
                    "compaction_strategy, summary_json FROM chat_session_memories "
                    "WHERE compacted_through_event_id > 0"
                )
            ).mappings().all()
            snapshot_rows = [
                {
                    "session_id": int(row["session_id"]),
                    "source_start_event_id": 0,
                    "compacted_through_event_id": int(row["compacted_through_event_id"] or 0),
                    "compacted_through_message_id": int(row["compacted_through_message_id"] or 0),
                    "retained_from_event_id": int(row["compacted_through_event_id"] or 0) + 1,
                    "summary_json": row["summary_json"] or "{}",
                    "strategy": row["compaction_strategy"] or "legacy",
                    "trigger": "migration",
                    "input_budget_tokens": 0,
                    "is_active": True,
                    "active_slot": 1,
                    "invalidation_reason": "",
                }
                for row in legacy_snapshot_rows
                if int(row["session_id"]) not in existing_snapshot_sessions
            ]
            if snapshot_rows:
                connection.execute(ChatContextSnapshot.__table__.insert(), snapshot_rows)

        # Anchor legacy snapshots to the active canonical event prefix. A
        # snapshot which includes an already-retired suffix cannot be proven
        # safe and is deliberately left inactive for a future model rebuild.
        if inspector.has_table("chat_context_snapshots"):
            snapshots = connection.execute(
                text(
                    "SELECT id, session_id, compacted_through_event_id, source_event_count, source_prefix_hash "
                    "FROM chat_context_snapshots"
                )
            ).mappings().all()
            for snapshot in snapshots:
                if int(snapshot["source_event_count"] or 0) and str(snapshot["source_prefix_hash"] or ""):
                    continue
                cutoff = int(snapshot["compacted_through_event_id"] or 0)
                if cutoff <= 0:
                    continue
                session_row = connection.execute(
                    text("SELECT context_start_message_id, context_generation FROM chat_sessions WHERE id = :session_id"),
                    {"session_id": snapshot["session_id"]},
                ).mappings().first()
                if not session_row:
                    continue
                retired = connection.execute(
                    text(
                        "SELECT 1 FROM chat_context_events e JOIN chat_messages m ON e.message_id = m.id "
                        "WHERE e.session_id = :session_id AND e.id <= :cutoff AND m.is_superseded = 1 LIMIT 1"
                    ),
                    {"session_id": snapshot["session_id"], "cutoff": cutoff},
                ).scalar()
                if retired:
                    connection.execute(
                        text(
                            "UPDATE chat_context_snapshots SET is_active = 0, active_slot = NULL, invalidation_reason = 'legacy_source_hidden' "
                            "WHERE id = :id"
                        ),
                        {"id": snapshot["id"]},
                    )
                    continue
                event_rows = connection.execute(
                    text(
                        "SELECT e.id, e.message_id, e.kind, e.payload_json, e.document_revision, e.is_legacy "
                        "FROM chat_context_events e JOIN chat_messages m ON e.message_id = m.id "
                        "WHERE e.session_id = :session_id AND m.is_superseded = 0 "
                        "AND e.id <= :cutoff AND (:start = 0 OR e.message_id > :start) ORDER BY e.id"
                    ),
                    {
                        "session_id": snapshot["session_id"],
                        "cutoff": cutoff,
                        "start": int(session_row["context_start_message_id"] or 0),
                    },
                ).mappings().all()
                if not event_rows:
                    continue
                connection.execute(
                    text(
                        "UPDATE chat_context_snapshots SET source_event_count = :count, source_prefix_hash = :hash, "
                        "context_generation = :generation WHERE id = :id"
                    ),
                    {
                        "id": snapshot["id"],
                        "count": len(event_rows),
                        "hash": _legacy_snapshot_prefix_hash([dict(row) for row in event_rows]),
                        "generation": int(session_row["context_generation"] or 0),
                    },
                )

        # Legacy releases could create two active summaries under concurrent
        # compaction.  Preserve the newest one, retire the others, then add a
        # portable partial-unique equivalent using the nullable active slot.
        if inspector.has_table("chat_context_snapshots"):
            active_rows = connection.execute(
                text("SELECT id, session_id FROM chat_context_snapshots WHERE is_active = 1 ORDER BY id")
            ).mappings().all()
            newest_by_session: dict[int, int] = {}
            for row in active_rows:
                newest_by_session[int(row["session_id"])] = int(row["id"])
            for row in active_rows:
                snapshot_id = int(row["id"])
                if newest_by_session[int(row["session_id"])] == snapshot_id:
                    continue
                connection.execute(
                    text(
                        "UPDATE chat_context_snapshots SET is_active = 0, active_slot = NULL, "
                        "invalidation_reason = CASE WHEN invalidation_reason = '' THEN 'migration_deduplicated' "
                        "ELSE invalidation_reason END WHERE id = :id"
                    ),
                    {"id": snapshot_id},
                )
            connection.execute(text("UPDATE chat_context_snapshots SET active_slot = NULL WHERE is_active = 0"))
            connection.execute(text("UPDATE chat_context_snapshots SET active_slot = 1 WHERE is_active = 1"))
            snapshot_indexes = {index["name"] for index in inspect(connection).get_indexes("chat_context_snapshots")}
            snapshot_indexes.update(
                constraint["name"]
                for constraint in inspect(connection).get_unique_constraints("chat_context_snapshots")
                if constraint.get("name")
            )
            if "uq_chat_context_snapshots_active_slot" not in snapshot_indexes:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX uq_chat_context_snapshots_active_slot "
                        "ON chat_context_snapshots (session_id, active_slot)"
                    )
                )

        # Existing superseded messages were created before read-only archives
        # existed. Group each legacy session suffix once without changing its
        # immutable event/tool payloads.
        if inspector.has_table("chat_history_archives"):
            archived_sessions = connection.execute(
                text("SELECT DISTINCT session_id FROM chat_messages WHERE is_superseded = 1 AND history_archive_id IS NULL")
            ).scalars().all()
            for session_id in archived_sessions:
                first_message_id = connection.execute(
                    text(
                        "SELECT MIN(id) FROM chat_messages "
                        "WHERE session_id = :session_id AND is_superseded = 1 AND history_archive_id IS NULL"
                    ),
                    {"session_id": session_id},
                ).scalar()
                if first_message_id is None:
                    continue
                result = connection.execute(
                    ChatHistoryArchive.__table__.insert().values(
                        session_id=int(session_id), source_message_id=int(first_message_id), reason="legacy"
                    )
                )
                archive_id = int(result.inserted_primary_key[0])
                connection.execute(
                    text(
                        "UPDATE chat_messages SET history_archive_id = :archive_id "
                        "WHERE session_id = :session_id AND is_superseded = 1 AND history_archive_id IS NULL"
                    ),
                    {"archive_id": archive_id, "session_id": session_id},
                )

        # Questions created before inactivity handling have no deadline. Their
        # creation time remains the fallback inactivity start; new questions
        # receive both timestamps atomically with the pause.
        if inspector.has_table("chat_user_questions"):
            question_columns = {
                column["name"] for column in inspect(connection).get_columns("chat_user_questions")
            }
            question_time_column = "DATETIME" if is_sqlite else "DATETIME(6) NULL"
            for column_name in ("last_activity_at", "timeout_at"):
                if column_name not in question_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE chat_user_questions ADD COLUMN {column_name} "
                            f"{question_time_column}"
                        )
                    )
            question_indexes = {
                index["name"] for index in inspect(connection).get_indexes("chat_user_questions")
            }
            if "ix_chat_user_questions_timeout_at" not in question_indexes:
                connection.execute(
                    text("CREATE INDEX ix_chat_user_questions_timeout_at ON chat_user_questions (timeout_at)")
                )

            # ``run_id`` used to be unique, which made a second sequential
            # ask_user call in the same Agent run fail with MySQL 1062.  A run
            # may have many answered questions but exactly one live one due to
            # the run status transition; de-duplicate the individual tool call
            # instead. SQLite cannot drop an inline UNIQUE constraint, so
            # rebuild this one small table from a temporary copy.
            question_inspector = inspect(connection)
            question_unique_constraints = {
                constraint["name"]
                for constraint in question_inspector.get_unique_constraints("chat_user_questions")
                if constraint.get("name")
            }
            question_index_names = {
                index["name"] for index in question_inspector.get_indexes("chat_user_questions")
            }
            if "uq_chat_user_questions_run" in (question_unique_constraints | question_index_names):
                if is_sqlite:
                    copy_columns = ", ".join(ChatUserQuestion.__table__.columns.keys())
                    connection.execute(
                        text(
                            "CREATE TEMPORARY TABLE chat_user_questions_run_unique_backup "
                            f"AS SELECT {copy_columns} FROM chat_user_questions"
                        )
                    )
                    connection.execute(text("DROP TABLE chat_user_questions"))
                    ChatUserQuestion.__table__.create(bind=connection, checkfirst=False)
                    connection.execute(
                        text(
                            f"INSERT INTO chat_user_questions ({copy_columns}) "
                            f"SELECT {copy_columns} FROM chat_user_questions_run_unique_backup"
                        )
                    )
                    connection.execute(text("DROP TABLE chat_user_questions_run_unique_backup"))
                else:
                    connection.execute(text("ALTER TABLE chat_user_questions DROP INDEX uq_chat_user_questions_run"))

            question_inspector = inspect(connection)
            question_indexes = {
                index["name"] for index in question_inspector.get_indexes("chat_user_questions")
            }
            question_unique_constraints = {
                constraint["name"]
                for constraint in question_inspector.get_unique_constraints("chat_user_questions")
                if constraint.get("name")
            }
            all_question_index_names = question_indexes | question_unique_constraints
            if "ix_chat_user_questions_run_id" not in all_question_index_names:
                connection.execute(text("CREATE INDEX ix_chat_user_questions_run_id ON chat_user_questions (run_id)"))
            if "uq_chat_user_questions_run_call" not in all_question_index_names:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX uq_chat_user_questions_run_call "
                        "ON chat_user_questions (run_id, tool_call_id)"
                    )
                )

            # Earlier streaming events used ``tool-{turn}-{index}``, whose
            # turn counter restarted after each user answer.  Completed runs
            # could therefore collapse several ask_user calls into one stale
            # timeline entry. Restore every recorded answered question before
            # normal historical rendering turns it into a false failure.
            if inspector.has_table("chat_messages") and inspector.has_table("agent_runs"):
                answered_questions = connection.execute(
                    text(
                        "SELECT r.assistant_message_id AS message_id, q.tool_call_id, q.answer_json "
                        "FROM agent_runs r "
                        "JOIN chat_user_questions q ON q.run_id = r.id "
                        "WHERE r.assistant_message_id IS NOT NULL AND UPPER(q.status) = 'ANSWERED' "
                        "ORDER BY r.assistant_message_id, q.answered_at, q.created_at, q.id"
                    )
                ).mappings().all()
                answered_by_message: dict[int, list[tuple[str, dict]]] = {}
                for row in answered_questions:
                    message_id = int(row["message_id"])
                    try:
                        answer = json.loads(row["answer_json"] or "{}")
                    except json.JSONDecodeError:
                        answer = {}
                    answered_by_message.setdefault(message_id, []).append(
                        (str(row["tool_call_id"] or ""), answer if isinstance(answer, dict) else {})
                    )
                for message_id, answered_items in answered_by_message.items():
                    tool_call_ids = [item[0] for item in answered_items]
                    answers_by_tool_call_id = {item[0]: item[1] for item in answered_items if item[0]}
                    message_row = connection.execute(
                        text(
                            "SELECT tool_calls_json, turn_blocks_json FROM chat_messages "
                            "WHERE id = :message_id"
                        ),
                        {"message_id": message_id},
                    ).mappings().first()
                    if message_row is None:
                        continue
                    try:
                        tool_calls = json.loads(message_row["tool_calls_json"] or "[]")
                        turn_blocks = json.loads(message_row["turn_blocks_json"] or "[]")
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(tool_calls, list) or not isinstance(turn_blocks, list):
                        continue
                    if not _repair_answered_user_question_timeline(
                        tool_calls,
                        turn_blocks,
                        tool_call_ids,
                        answers_by_tool_call_id,
                    ):
                        continue
                    connection.execute(
                        text(
                            "UPDATE chat_messages SET tool_calls_json = :tool_calls, "
                            "turn_blocks_json = :turn_blocks WHERE id = :message_id"
                        ),
                        {
                            "message_id": message_id,
                            "tool_calls": json.dumps(tool_calls, ensure_ascii=False),
                            "turn_blocks": json.dumps(turn_blocks, ensure_ascii=False),
                        },
                    )

        run_columns = {column["name"] for column in inspect(connection).get_columns("agent_runs")}
        # SQLAlchemy stores enum member names in native MySQL ENUM columns.
        # Existing deployments need the new waiting state before a paused run
        # can be persisted.
        if not is_sqlite and "status" in run_columns:
            status_column = {column["name"]: column for column in inspect(connection).get_columns("agent_runs")}.get("status")
            status_values = set(getattr(status_column["type"], "enums", ()) if status_column else ())
            required_status_values = {"PENDING", "RUNNING", "WAITING_FOR_INPUT", "CANCELLING", "COMPLETED", "CANCELLED", "FAILED"}
            if not required_status_values.issubset(status_values):
                enum_definition = ", ".join(f"'{value}'" for value in sorted(required_status_values))
                connection.execute(text(f"ALTER TABLE agent_runs MODIFY COLUMN status ENUM({enum_definition}) NOT NULL"))
        if "session_id" not in run_columns:
            run_session_column = "INTEGER" if is_sqlite else "BIGINT UNSIGNED NULL"
            connection.execute(text(f"ALTER TABLE agent_runs ADD COLUMN session_id {run_session_column}"))
        if "checkpoint_html" not in run_columns:
            checkpoint_column = "TEXT NOT NULL DEFAULT ''" if is_sqlite else "LONGTEXT NULL"
            connection.execute(text(f"ALTER TABLE agent_runs ADD COLUMN checkpoint_html {checkpoint_column}"))
            if not is_sqlite:
                connection.execute(text("UPDATE agent_runs SET checkpoint_html = '' WHERE checkpoint_html IS NULL"))
        run_column_definitions = (
            {
                "owner_id": "TEXT NOT NULL DEFAULT ''",
                "lease_expires_at": "DATETIME",
                "heartbeat_at": "DATETIME",
                "cancel_requested_at": "DATETIME",
                "worker_pid": "INTEGER",
                "last_phase": "TEXT NOT NULL DEFAULT ''",
                "last_progress_at": "DATETIME",
                "event_sequence": "INTEGER NOT NULL DEFAULT 0",
            }
            if is_sqlite
            else {
                "owner_id": "VARCHAR(160) NOT NULL DEFAULT ''",
                "lease_expires_at": "DATETIME(6) NULL",
                "heartbeat_at": "DATETIME(6) NULL",
                "cancel_requested_at": "DATETIME(6) NULL",
                "worker_pid": "INT NULL",
                "last_phase": "VARCHAR(64) NOT NULL DEFAULT ''",
                "last_progress_at": "DATETIME(6) NULL",
                "event_sequence": "INT NOT NULL DEFAULT 0",
            }
        )
        for column_name, definition in run_column_definitions.items():
            if column_name not in run_columns:
                connection.execute(text(f"ALTER TABLE agent_runs ADD COLUMN {column_name} {definition}"))
        # A deployment can add ``event_sequence`` while an older worker still
        # has events in flight.  Bring each allocation cursor up to the
        # durable high-water mark before the new workers begin appending.
        if inspector.has_table("agent_run_events"):
            if is_sqlite:
                connection.execute(
                    text(
                        "UPDATE agent_runs SET event_sequence = "
                        "(SELECT MAX(sequence) FROM agent_run_events "
                        "WHERE agent_run_events.run_id = agent_runs.id) "
                        "WHERE COALESCE(event_sequence, 0) < COALESCE("
                        "(SELECT MAX(sequence) FROM agent_run_events "
                        "WHERE agent_run_events.run_id = agent_runs.id), 0)"
                    )
                )
            else:
                connection.execute(
                    text(
                        "UPDATE agent_runs AS runs "
                        "JOIN (SELECT run_id, MAX(sequence) AS max_sequence "
                        "FROM agent_run_events GROUP BY run_id) AS events "
                        "ON events.run_id = runs.id "
                        "SET runs.event_sequence = GREATEST(COALESCE(runs.event_sequence, 0), events.max_sequence)"
                    )
                )
        unassigned_runs = connection.execute(
            text("SELECT id, document_id, user_message_id FROM agent_runs WHERE session_id IS NULL")
        ).mappings().all()
        for run in unassigned_runs:
            message_session = connection.execute(
                text("SELECT session_id FROM chat_messages WHERE id = :message_id"),
                {"message_id": run["user_message_id"]},
            ).scalar()
            session_id = int(message_session) if message_session else session_by_document.get(int(run["document_id"]))
            if session_id:
                connection.execute(
                    text("UPDATE agent_runs SET session_id = :session_id WHERE id = :run_id"),
                    {"session_id": session_id, "run_id": run["id"]},
                )
        run_indexes = {index["name"] for index in inspect(connection).get_indexes("agent_runs")}
        if "ix_agent_runs_session_id" not in run_indexes:
            connection.execute(text("CREATE INDEX ix_agent_runs_session_id ON agent_runs (session_id)"))
        if "ix_agent_runs_lease_expires_at" not in run_indexes:
            connection.execute(text("CREATE INDEX ix_agent_runs_lease_expires_at ON agent_runs (lease_expires_at)"))

        if inspector.has_table("model_call_records"):
            model_call_columns = {
                column["name"]: column for column in inspect(connection).get_columns("model_call_records")
            }
            if not is_sqlite:
                status_column = model_call_columns.get("status")
                status_values = set(getattr(status_column["type"], "enums", ()) if status_column else ())
                required_status_values = {"running", "completed", "failed", "cancelled", "abandoned"}
                if not required_status_values.issubset(status_values):
                    enum_definition = ", ".join(f"'{value}'" for value in sorted(required_status_values))
                    connection.execute(
                        text(
                            "ALTER TABLE model_call_records MODIFY COLUMN "
                            f"status ENUM({enum_definition}) NOT NULL"
                        )
                    )
                finished_column = model_call_columns.get("finished_at")
                if finished_column is not None and not bool(finished_column.get("nullable", False)):
                    connection.execute(text("ALTER TABLE model_call_records MODIFY COLUMN finished_at DATETIME(6) NULL"))

        # Preserve prior document-level automatic summaries only for the
        # backfilled initial conversation. New code never reads this legacy
        # table, preventing any cross-session memory leakage.
        legacy_memories = connection.execute(
            text("SELECT document_id, compacted_through_message_id, summary_json FROM document_agent_memories")
        ).mappings().all()
        existing_memory_sessions = set(connection.execute(text("SELECT session_id FROM chat_session_memories")).scalars().all())
        to_copy = [
            {
                "session_id": session_by_document[int(memory["document_id"])],
                "compacted_through_message_id": int(memory["compacted_through_message_id"] or 0),
                "summary_json": memory["summary_json"] or "{}",
            }
            for memory in legacy_memories
            if int(memory["document_id"]) in session_by_document
            and session_by_document[int(memory["document_id"])] not in existing_memory_sessions
        ]
        if to_copy:
            connection.execute(ChatSessionMemory.__table__.insert(), to_copy)

        # Convert the old display transcript into provider-visible events once.
        # Legacy tool results are less precise than the new live capture, but
        # preserving their ordering lets old sessions grow and compact without
        # contaminating another session's context.
        existing_event_message_ids = set(
            connection.execute(
                text("SELECT DISTINCT message_id FROM chat_context_events WHERE message_id IS NOT NULL")
            ).scalars().all()
        )
        legacy_messages = connection.execute(
            text(
                "SELECT id, document_id, session_id, role, content, tool_calls_json "
                "FROM chat_messages WHERE session_id IS NOT NULL ORDER BY session_id, id"
            )
        ).mappings().all()
        event_rows = []
        for message in legacy_messages:
            message_id = int(message["id"])
            if message_id in existing_event_message_ids:
                continue
            # SQLAlchemy's Enum persists member names on MySQL by default
            # (``USER``/``ASSISTANT``), while imported SQLite data may hold
            # their lowercase values. Treat both representations identically.
            role = str(message["role"] or "").lower()
            if role == "user":
                event_rows.append(
                    {
                        "document_id": int(message["document_id"]),
                        "session_id": int(message["session_id"]),
                        "message_id": message_id,
                        "ordinal": 0,
                        "kind": ContextEventKind.USER.value,
                        "payload_json": json.dumps({"content": message["content"] or ""}, ensure_ascii=False),
                        "document_revision": "",
                        "is_legacy": True,
                    }
                )
                continue
            if role != "assistant":
                continue
            try:
                tools = json.loads(message["tool_calls_json"] or "[]")
            except json.JSONDecodeError:
                tools = []
            tools = tools if isinstance(tools, list) else []
            ordinal = 0
            for index, tool in enumerate(tools):
                if not isinstance(tool, dict):
                    continue
                call_id = str(tool.get("id") or f"legacy-{message_id}-{index}")
                name = str(tool.get("name") or "unknown")
                arguments = tool.get("arguments") if isinstance(tool.get("arguments"), dict) else {}
                activity = tool.get("activity") if isinstance(tool.get("activity"), dict) else {}
                revision = str(activity.get("revision") or "")
                if not revision:
                    try:
                        result_payload = json.loads(str(tool.get("result") or ""))
                        if isinstance(result_payload, dict):
                            revision = str(result_payload.get("revision") or result_payload.get("current_revision") or "")
                    except json.JSONDecodeError:
                        pass
                event_rows.append(
                    {
                        "document_id": int(message["document_id"]),
                        "session_id": int(message["session_id"]),
                        "message_id": message_id,
                        "ordinal": ordinal,
                        "kind": ContextEventKind.ASSISTANT.value,
                        "payload_json": json.dumps({"content": "", "tool_calls": [{"id": call_id, "name": name, "args": arguments}]}, ensure_ascii=False),
                        "document_revision": "",
                        "is_legacy": True,
                    }
                )
                ordinal += 1
                event_rows.append(
                    {
                        "document_id": int(message["document_id"]),
                        "session_id": int(message["session_id"]),
                        "message_id": message_id,
                        "ordinal": ordinal,
                        "kind": ContextEventKind.TOOL.value,
                        "payload_json": json.dumps(
                            {
                                "content": str(tool.get("result") or "历史工具已执行；如需当前定位请重新读取工作区。"),
                                "tool_call_id": call_id,
                                "name": name,
                                "status": "error" if tool.get("status") == "error" else "success",
                            },
                            ensure_ascii=False,
                        ),
                        "document_revision": revision,
                        "is_legacy": True,
                    }
                )
                ordinal += 1
            if message["content"]:
                event_rows.append(
                    {
                        "document_id": int(message["document_id"]),
                        "session_id": int(message["session_id"]),
                        "message_id": message_id,
                        "ordinal": ordinal,
                        "kind": ContextEventKind.ASSISTANT.value,
                        "payload_json": json.dumps({"content": message["content"]}, ensure_ascii=False),
                        "document_revision": "",
                        "is_legacy": True,
                    }
                )
        if event_rows:
            connection.execute(ChatContextEvent.__table__.insert(), event_rows)

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "password_change_required" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN password_change_required BOOLEAN NOT NULL DEFAULT 0")
            )
            rows = connection.execute(text("SELECT id, username, password_hash FROM users")).mappings().all()
            for row in rows:
                if password_hash_requires_change(str(row["username"]), str(row["password_hash"])):
                    connection.execute(
                        text("UPDATE users SET password_change_required = 1 WHERE id = :user_id"),
                        {"user_id": row["id"]},
                    )

        # This project still has a deliberately idempotent compatibility
        # migrator rather than Alembic.  Record the completed contract so
        # workers and readiness probes can reject partially bootstrapped DBs.
        connection.execute(
            text(f"{lock_insert} INTO schema_migrations (version) VALUES (:version)"),
            {"version": SCHEMA_REVISION},
        )

        memory_rows = connection.execute(
            text("SELECT id, session_id, compacted_through_message_id FROM chat_session_memories")
        ).mappings().all()
        for memory in memory_rows:
            if not memory["compacted_through_message_id"]:
                continue
            event_id = connection.execute(
                text(
                    "SELECT MAX(id) FROM chat_context_events "
                    "WHERE session_id = :session_id AND message_id <= :message_id"
                ),
                {"session_id": memory["session_id"], "message_id": memory["compacted_through_message_id"]},
            ).scalar()
            if event_id:
                connection.execute(
                    text(
                        "UPDATE chat_session_memories SET compacted_through_event_id = :event_id "
                        "WHERE id = :memory_id AND compacted_through_event_id = 0"
                    ),
                    {"event_id": event_id, "memory_id": memory["id"]},
                )

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "display_name" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN display_name VARCHAR(64) NOT NULL DEFAULT ''")
            )

        document_columns = {column["name"]: column for column in inspector.get_columns("documents")}
        if is_sqlite:
            document_column_definitions = {
                "group_id": "INTEGER",
                "created_by_id": "INTEGER",
                "last_modified_by_id": "INTEGER",
                "visibility_mode": "VARCHAR(16) NOT NULL DEFAULT 'all'",
                "source_object_key": "VARCHAR(1024)",
                "source_filename": "VARCHAR(512)",
                "source_content_type": "VARCHAR(128)",
                "source_size": "INTEGER",
                "wechat_title": "VARCHAR(256) NOT NULL DEFAULT ''",
                "wechat_author": "VARCHAR(16) NOT NULL DEFAULT ''",
                "wechat_digest": "VARCHAR(120) NOT NULL DEFAULT ''",
                "wechat_content_source_url": "VARCHAR(1024) NOT NULL DEFAULT ''",
                "wechat_cover_url": "VARCHAR(2048) NOT NULL DEFAULT ''",
                "wechat_pic_crop_235_1": "VARCHAR(128) NOT NULL DEFAULT ''",
                "wechat_pic_crop_1_1": "VARCHAR(128) NOT NULL DEFAULT ''",
                "wechat_need_open_comment": "BOOLEAN NOT NULL DEFAULT 0",
                "wechat_only_fans_can_comment": "BOOLEAN NOT NULL DEFAULT 0",
            }
        else:
            document_column_definitions = {
                "group_id": "BIGINT UNSIGNED NULL",
                "created_by_id": "BIGINT UNSIGNED NULL",
                "last_modified_by_id": "BIGINT UNSIGNED NULL",
                "visibility_mode": "VARCHAR(16) NOT NULL DEFAULT 'all'",
                "source_object_key": "VARCHAR(1024) NULL",
                "source_filename": "VARCHAR(512) NULL",
                "source_content_type": "VARCHAR(128) NULL",
                "source_size": "INT NULL",
                "wechat_title": "VARCHAR(256) NOT NULL DEFAULT ''",
                "wechat_author": "VARCHAR(16) NOT NULL DEFAULT ''",
                "wechat_digest": "VARCHAR(120) NOT NULL DEFAULT ''",
                "wechat_content_source_url": "VARCHAR(1024) NOT NULL DEFAULT ''",
                "wechat_cover_url": "VARCHAR(2048) NOT NULL DEFAULT ''",
                "wechat_pic_crop_235_1": "VARCHAR(128) NOT NULL DEFAULT ''",
                "wechat_pic_crop_1_1": "VARCHAR(128) NOT NULL DEFAULT ''",
                "wechat_need_open_comment": "TINYINT(1) NOT NULL DEFAULT 0",
                "wechat_only_fans_can_comment": "TINYINT(1) NOT NULL DEFAULT 0",
            }
        for column_name, definition in document_column_definitions.items():
            if column_name not in document_columns:
                connection.execute(text(f"ALTER TABLE documents ADD COLUMN {column_name} {definition}"))
        if not is_sqlite:
            wechat_title_column = document_columns.get("wechat_title")
            current_length = getattr(wechat_title_column["type"], "length", None) if wechat_title_column else None
            if current_length is not None and current_length < 256:
                connection.execute(text("ALTER TABLE documents MODIFY COLUMN wechat_title VARCHAR(256) NOT NULL DEFAULT ''"))
        connection.execute(text("UPDATE documents SET wechat_title = title WHERE wechat_title <> title"))

        document_version_columns = {column["name"] for column in inspector.get_columns("document_versions")}
        if "content_object_id" not in document_version_columns:
            version_content_type = "INTEGER" if is_sqlite else "BIGINT UNSIGNED NULL"
            connection.execute(text(f"ALTER TABLE document_versions ADD COLUMN content_object_id {version_content_type}"))
        version_indexes = {index["name"] for index in inspector.get_indexes("document_versions")}
        if "ix_document_versions_content_object_id" not in version_indexes:
            connection.execute(text("CREATE INDEX ix_document_versions_content_object_id ON document_versions (content_object_id)"))

        document_group_columns = {column["name"] for column in inspector.get_columns("document_groups")}
        if "visibility_mode" not in document_group_columns:
            connection.execute(
                text("ALTER TABLE document_groups ADD COLUMN visibility_mode VARCHAR(16) NOT NULL DEFAULT 'all'")
            )

        # 旧数据只有 owner_id；将它保留为历史文档的创建人与最后修改人。
        connection.execute(
            text("UPDATE users SET display_name = username WHERE display_name IS NULL OR TRIM(display_name) = ''")
        )
        connection.execute(
            text("UPDATE documents SET created_by_id = owner_id WHERE created_by_id IS NULL")
        )
        connection.execute(
            text("UPDATE documents SET last_modified_by_id = owner_id WHERE last_modified_by_id IS NULL")
        )

        # 版本功能上线前已存在的文档没有历史快照。保留其当前稿作为可恢复的 v1，
        # 已有版本的文档不受影响。
        document_version_table = DocumentVersion.__table__
        existing_document_ids = (
            connection.execute(text("SELECT id FROM documents"))
            .scalars()
            .all()
        )
        versioned_document_ids = set(
            connection.execute(text("SELECT DISTINCT document_id FROM document_versions"))
            .scalars()
            .all()
        )
        missing_document_ids = [document_id for document_id in existing_document_ids if document_id not in versioned_document_ids]
        if missing_document_ids:
            documents = connection.execute(
                text(
                    "SELECT id, title, current_html, last_modified_by_id "
                    "FROM documents WHERE id IN :document_ids"
                ).bindparams(bindparam("document_ids", expanding=True)),
                {"document_ids": missing_document_ids},
            ).mappings()
            connection.execute(
                document_version_table.insert(),
                [
                    {
                        "document_id": document["id"],
                        "version_number": 1,
                        "title": document["title"],
                        "html": document["current_html"],
                        "source": DocumentVersionSource.INITIAL,
                        "label": "启用版本管理时的当前稿",
                        "created_by_id": document["last_modified_by_id"],
                    }
                    for document in documents
                ],
            )

        # Version rows from older releases contain a full HTML copy. Convert
        # them in place so future history reads use the shared object store.
        # Keep legacy-version repair isolated from the outer migration
        # transaction. Closing a Session bound directly to ``connection``
        # would otherwise roll back SQLite's pending DDL/DML.
        migration_session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            migrate_legacy_document_versions(migration_session)
            migration_session.flush()
        finally:
            migration_session.close()

        # Older AI/manual saves wrote UTC wall time into MySQL DATETIME while
        # version rows used the database clock. Restore the invariant that a
        # document cannot predate its latest persisted edit.
        repair_document_activity_timestamps(connection)

        # Older messages did not retain an author. Every persisted user turn
        # has an AgentRun, which is the authoritative historical owner. This
        # must run after closing the bound ORM session above: SQLite rolls back
        # its pending DML when that session closes, while retaining prior DDL.
        connection.execute(
            text(
                "UPDATE chat_messages SET created_by_id = ("
                "SELECT user_id FROM agent_runs "
                "WHERE agent_runs.user_message_id = chat_messages.id"
                ") WHERE created_by_id IS NULL"
            )
        )


def seed_default_admin(db: Session) -> None:
    settings = get_settings()
    has_any_user = db.query(User).first() is not None
    if has_any_user:
        return
    admin = User(
        username=settings.DEFAULT_ADMIN_USERNAME,
        display_name=settings.DEFAULT_ADMIN_USERNAME,
        password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
        password_change_required=is_forced_password_change_value(
            settings.DEFAULT_ADMIN_USERNAME, settings.DEFAULT_ADMIN_PASSWORD
        ),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    print(f"[bootstrap] 已创建默认管理员账号: {settings.DEFAULT_ADMIN_USERNAME}（请首次登录后立即修改密码）")


def backfill_official_deepseek_thinking_models(db: Session) -> int:
    """Upgrade unconfigured official DeepSeek models without touching custom mappings."""
    changed = 0
    providers = db.query(AIProvider).all()
    for provider in providers:
        if not is_official_deepseek_openai_endpoint(provider.base_url):
            continue
        for model in provider.models:
            if not model.thinking_config:
                model.thinking_config = official_deepseek_thinking_config()
                changed += 1
            if not model.supports_disabled_thinking:
                model.supports_disabled_thinking = True
                changed += 1
    if changed:
        db.commit()
    return changed


def migrate_anthropic_thinking_models(db: Session) -> int:
    """Replace legacy OpenAI reasoning mappings on Anthropic providers.

    Previous management UI releases generated ``reasoning_effort`` for every
    provider. Anthropic Messages uses adaptive thinking plus ``effort``
    instead, so repair only configurations that demonstrably use that legacy
    OpenAI field and leave native administrator configurations untouched.
    """
    changed = 0
    providers = db.query(AIProvider).filter(AIProvider.provider_type == ProviderType.ANTHROPIC).all()
    for provider in providers:
        for model in provider.models:
            config = model.thinking_config if isinstance(model.thinking_config, dict) else {}
            entries = [config.get("enabled"), config.get("disabled")]
            effort_entries = config.get("efforts")
            if isinstance(effort_entries, dict):
                entries.extend(effort_entries.values())
            if not any(isinstance(entry, dict) and "reasoning_effort" in entry for entry in entries):
                continue
            selected_efforts = (
                [str(effort) for effort in effort_entries if str(effort) in {"low", "medium", "high", "xhigh", "max"}]
                if isinstance(effort_entries, dict)
                else None
            )
            enabled = config.get("enabled")
            default_effort = enabled.get("reasoning_effort") if isinstance(enabled, dict) else None
            model.thinking_config = anthropic_adaptive_thinking_config(
                selected_efforts, str(default_effort or "")
            )
            if model.default_thinking_effort not in {"auto", "low", "medium", "high", "xhigh", "max"}:
                model.default_thinking_effort = "auto"
            changed += 1
    if changed:
        db.commit()
    return changed


def migrate_gemini_native_providers(db: Session) -> int:
    """Move the bundled Google OpenAI-compatible preset to native Gemini API."""
    legacy_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    native_url = "https://generativelanguage.googleapis.com/v1beta"
    changed = 0
    providers = db.query(AIProvider).filter(AIProvider.base_url == legacy_url).all()
    for provider in providers:
        # Only the exact bundled URL is migrated. Third-party gateways may use
        # the same path but do not necessarily implement GenerateContent.
        provider.base_url = native_url
        provider.provider_type = ProviderType.GEMINI_NATIVE
        changed += 1
        for model in provider.models:
            is_gemini_3 = model.model_name.lower().startswith("gemini-3")
            model.thinking_config = (
                _gemini_3_thinking_config() if is_gemini_3 else _gemini_25_thinking_config()
            )
            if is_gemini_3:
                model.supports_disabled_thinking = False
                if model.default_thinking_effort not in {"auto", "low", "high"}:
                    model.default_thinking_effort = "auto"
            elif model.default_thinking_effort not in {"auto", "minimal", "low", "medium", "high", "max"}:
                model.default_thinking_effort = "auto"
            changed += 1
    if changed:
        db.commit()
    return changed


def recover_expired_agent_runs(db: Session) -> int:
    """Finish runs whose worker lease expired without replaying side effects.

    The worker itself is intentionally not resumed. A completed write tool has
    already checkpointed a full HTML candidate, so it can be committed only
    when the document still matches the request's starting snapshot.
    """
    now = datetime.now(timezone.utc)
    active_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.status.in_([AgentRunStatus.PENDING, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING]),
            (
                (AgentRun.owner_id == "")
                | (AgentRun.lease_expires_at.is_(None))
                | (AgentRun.lease_expires_at <= now)
            ),
        )
        .order_by(AgentRun.created_at)
        .all()
    )
    recovered = 0
    for candidate in active_runs:
        # The query above discovers candidates. Re-lock the run itself before
        # editing its document so two workers cannot recover the same lease.
        run = db.query(AgentRun).filter(AgentRun.id == candidate.id).with_for_update().first()
        if run is None:
            continue
        lease_expires_at = getattr(run, "lease_expires_at", None)
        if lease_expires_at is not None:
            lease_expires_at = (
                lease_expires_at.replace(tzinfo=timezone.utc)
                if lease_expires_at.tzinfo is None
                else lease_expires_at.astimezone(timezone.utc)
            )
        if (
            run.status not in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING}
            or (getattr(run, "owner_id", "") and lease_expires_at is not None and lease_expires_at > now)
        ):
            continue
        document = (
            db.query(Document)
            .filter(Document.id == run.document_id)
            .with_for_update()
            .first()
        )
        request_message = db.get(ChatMessage, run.user_message_id)
        checkpoint = str(run.checkpoint_html or "")
        source_html = request_message.html_before if request_message else None
        partial_saved = False
        if document and checkpoint and source_html is not None and document.current_html == source_html:
            document.current_html = checkpoint
            touch_document(document, run.user_id)
            if document.group:
                touch_group(document.group, run.user_id)
            create_document_version(
                db,
                document,
                run.user_id,
                DocumentVersionSource.AI,
                "AI 编辑（Agent 工作进程恢复）",
            )
            partial_saved = True

        if partial_saved:
            detail = "Agent 工作进程心跳已超时，未完成的操作已停止；已保留已完成的排版修改。"
        elif checkpoint:
            detail = "Agent 工作进程心跳已超时，未完成的操作已停止；文档已被其他修改更新，候选排版未自动覆盖。"
        else:
            detail = "Agent 工作进程心跳已超时，未完成的操作已停止；请重新执行本轮操作。"
        previous_phase = str(getattr(run, "last_phase", "") or "")
        run.status = AgentRunStatus.FAILED
        run.error_message = detail
        run.finished_at = datetime.now(timezone.utc)
        run.owner_id = ""
        run.lease_expires_at = None
        run.last_phase = "lease_expired"
        run.last_progress_at = run.finished_at
        running_calls = (
            db.query(ModelCallRecord)
            .filter(
                ModelCallRecord.source_id == run.id,
                ModelCallRecord.status == ModelCallStatus.RUNNING,
            )
            .all()
        )
        for call in running_calls:
            call.status = ModelCallStatus.ABANDONED
            call.finished_at = run.finished_at
            call.error_message = (
                "Agent worker lease expired before the model call completed; "
                f"run={run.id}; worker_pid={getattr(run, 'worker_pid', None) or 'unknown'}; "
                f"last_phase={previous_phase or 'unknown'}"
            )[:512]
        append_operation_log(
            db,
            actor=(
                db.get(User, user_id)
                if (user_id := getattr(run, "user_id", None)) is not None
                else None
            ),
            action="chat.run",
            resource_type="chat_run",
            resource_id=run.id,
            resource_name=str(getattr(document, "title", "")) if document else "",
            document_id=run.document_id,
            session_id=run.session_id,
            status=OperationLogStatus.FAILED,
            summary="AI 对话执行失败",
            error_summary="Agent 工作进程心跳超时",
            details={
                "document_changed": partial_saved,
                "recovered_after_worker_loss": True,
                "worker_pid": getattr(run, "worker_pid", None),
                "last_phase": previous_phase,
                "abandoned_model_calls": len(running_calls),
            },
            client_ip=str(getattr(run, "origin_client_ip", "")),
            user_agent=str(getattr(run, "origin_user_agent", "")),
        )
        assistant_content = detail
        if not run.assistant_message_id:
            events = (
                db.query(AgentRunEvent)
                .filter(AgentRunEvent.run_id == run.id)
                .order_by(AgentRunEvent.sequence)
                .all()
            )
            recovered_turn = recover_interrupted_turn(events, detail)
            assistant_message = ChatMessage(
                document_id=run.document_id,
                session_id=run.session_id,
                role=MessageRole.ASSISTANT,
                content=recovered_turn.content,
                tool_calls_json=json.dumps(recovered_turn.tool_calls, ensure_ascii=False),
                reasoning_trace_json=json.dumps(recovered_turn.reasoning_trace, ensure_ascii=False),
                turn_blocks_json=json.dumps(recovered_turn.turn_blocks, ensure_ascii=False),
                html_before=source_html,
                html_after=checkpoint if partial_saved else None,
            )
            db.add(assistant_message)
            db.flush()
            run.assistant_message_id = assistant_message.id
            assistant_content = assistant_message.content
        else:
            assistant_message = db.get(ChatMessage, run.assistant_message_id)
            if assistant_message:
                assistant_content = assistant_message.content

        # Recovery normally happens without the original worker's local SSE
        # cache. Store its terminal event with the same ordered event source so
        # a reconnect on either worker can render a definitive outcome.
        durable_sequence = (
            db.query(AgentRunEvent.sequence)
            .filter(AgentRunEvent.run_id == run.id)
            .order_by(AgentRunEvent.sequence.desc())
            .limit(1)
            .scalar()
        )
        run.event_sequence = max(int(getattr(run, "event_sequence", 0) or 0), int(durable_sequence or 0)) + 1
        report_html = document.current_html if document else checkpoint
        save_state = "preserved" if partial_saved else "conflict" if checkpoint else "none"
        db.add(
            AgentRunEvent(
                run_id=run.id,
                sequence=run.event_sequence,
                event="final",
                payload_json=json.dumps(
                    {
                        "content": assistant_content,
                        "html": report_html,
                        "html_changed": partial_saved,
                        "compliance": run_compliance_check(report_html).to_dict(),
                        "cancelled": False,
                        "partial": True,
                        "partial_save_state": save_state,
                        "run_status": AgentRunStatus.FAILED.value,
                        "error_message": detail,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def recover_interrupted_agent_runs(db: Session) -> int:
    """Compatibility entry point used by startup recovery."""
    return recover_expired_agent_runs(db)
