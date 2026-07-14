"""首次启动初始化逻辑与轻量 SQLite schema migration。"""
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import engine
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.user import User, UserRole


def migrate_schema() -> None:
    """补齐已发布数据库缺少的轻量字段。

    当前项目未引入 Alembic；新部署由 ``Base.metadata.create_all`` 创建完整结构，
    此处覆盖已有 SQLite/MySQL 库的向前兼容升级路径。
    """
    inspector = inspect(engine)
    is_sqlite = engine.url.drivername.startswith("sqlite")
    with engine.begin() as connection:
        # 后台任务不跨进程恢复。服务启动时明确结束遗留运行，避免它们永久占住文档锁。
        if inspect(engine).has_table("agent_runs"):
            connection.execute(
                AgentRun.__table__.update()
                .where(AgentRun.status.in_([AgentRunStatus.PENDING, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING]))
                .values(
                    status=AgentRunStatus.FAILED,
                    error_message="服务已重启，未完成的 Agent 已停止；请重新执行本轮操作",
                )
            )
        model_columns = {column["name"] for column in inspector.get_columns("ai_models")}
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
                text("ALTER TABLE ai_models ADD COLUMN tool_result_max_tokens INT NOT NULL DEFAULT 4096")
            )
        if "access_mode" not in model_columns:
            connection.execute(
                text("ALTER TABLE ai_models ADD COLUMN access_mode VARCHAR(16) NOT NULL DEFAULT 'all'")
            )
        message_columns = {column["name"] for column in inspector.get_columns("chat_messages")}
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
                "selected_elements_json": "TEXT NOT NULL DEFAULT '[]'",
                "turn_blocks_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            if is_sqlite
            else {
                "html_before": "LONGTEXT NULL",
                "html_after": "LONGTEXT NULL",
                "is_superseded": "TINYINT(1) NOT NULL DEFAULT 0",
                "selected_elements_json": "LONGTEXT NULL",
                "turn_blocks_json": "LONGTEXT NULL",
            }
        )
        for column_name, definition in message_column_definitions.items():
            if column_name not in message_columns:
                connection.execute(text(f"ALTER TABLE chat_messages ADD COLUMN {column_name} {definition}"))
        if "selected_elements_json" not in message_columns and not is_sqlite:
            connection.execute(
                text("UPDATE chat_messages SET selected_elements_json = '[]' WHERE selected_elements_json IS NULL")
            )
        if "turn_blocks_json" not in message_columns and not is_sqlite:
            connection.execute(
                text("UPDATE chat_messages SET turn_blocks_json = '[]' WHERE turn_blocks_json IS NULL")
            )

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "display_name" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN display_name VARCHAR(64) NOT NULL DEFAULT ''")
            )

        document_columns = {column["name"] for column in inspector.get_columns("documents")}
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
            }
        for column_name, definition in document_column_definitions.items():
            if column_name not in document_columns:
                connection.execute(text(f"ALTER TABLE documents ADD COLUMN {column_name} {definition}"))

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


def seed_default_admin(db: Session) -> None:
    settings = get_settings()
    has_any_user = db.query(User).first() is not None
    if has_any_user:
        return
    admin = User(
        username=settings.DEFAULT_ADMIN_USERNAME,
        display_name=settings.DEFAULT_ADMIN_USERNAME,
        password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    print(
        f"[bootstrap] 已创建默认管理员账号: {settings.DEFAULT_ADMIN_USERNAME} / "
        f"{settings.DEFAULT_ADMIN_PASSWORD} （请登录后立即修改密码）"
    )
