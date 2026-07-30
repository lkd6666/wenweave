"""将现有 SQLite 数据一次性迁移到空 MySQL 库。

使用示例（PowerShell）：
  $env:SOURCE_SQLITE_URL = 'sqlite:///./data/app.db'
  $env:TARGET_DATABASE_URL = 'mysql+pymysql://user:password@127.0.0.1:3306/yibanpaiban?charset=utf8mb4'
  python scripts/migrate_sqlite_to_mysql.py

脚本不会清空或覆盖目标库；检测到已有数据即停止，避免误操作。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select

# 允许从 backend 目录直接执行 ``python scripts/migrate_sqlite_to_mysql.py``。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401  注册所有表
from app.db.base import Base

TABLES_IN_ORDER = [
    "users",
    "user_groups",
    "user_group_members",
    "ai_providers",
    "ai_models",
    "model_user_access",
    "model_group_access",
    "storage_configs",
    "document_groups",
    "documents",
    "chat_sessions",
    "chat_messages",
    "agent_runs",
    "document_agent_memories",
    "chat_session_memories",
    "document_content_objects",
    "document_versions",
    "wechat_accounts",
    "wechat_account_user_access",
    "wechat_account_group_access",
    "wechat_body_image_materials",
    "wechat_cover_materials",
    "wechat_drafts",
]


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}")
    return value


def main() -> int:
    source_url = _required_env("SOURCE_SQLITE_URL")
    target_url = _required_env("TARGET_DATABASE_URL")
    if not source_url.startswith("sqlite"):
        raise RuntimeError("SOURCE_SQLITE_URL 必须是 SQLite 连接串")
    if not target_url.startswith("mysql+"):
        raise RuntimeError("TARGET_DATABASE_URL 必须是 mysql+pymysql 连接串")

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url, pool_pre_ping=True, pool_recycle=1800)
    Base.metadata.create_all(target_engine)

    metadata = Base.metadata
    source_metadata = MetaData()
    source_tables = set(inspect(source_engine).get_table_names())
    with source_engine.connect() as source, target_engine.begin() as target:
        for table_name in TABLES_IN_ORDER:
            table = metadata.tables[table_name]
            existing = target.execute(select(func.count()).select_from(table)).scalar_one()
            if existing:
                raise RuntimeError(f"目标表 {table_name} 已有 {existing} 条记录，迁移已停止")

            if table_name == "chat_sessions" and table_name not in source_tables:
                # Older releases stored one implicit conversation per document.
                # Materialize it before copying legacy chat_messages, whose new
                # session_id column is non-nullable in the target schema.
                document_rows = target.execute(select(metadata.tables["documents"].c.id)).mappings()
                compatible_rows = [
                    {"document_id": row["id"], "title": "初始对话", "is_archived": False, "context_start_message_id": 0}
                    for row in document_rows
                ]
                if compatible_rows:
                    target.execute(table.insert(), compatible_rows)
                print(f"{table_name}: {len(compatible_rows)} 条（由旧文档对话回填）")
                continue

            if table_name == "chat_session_memories" and table_name not in source_tables:
                legacy_memory_table = metadata.tables["document_agent_memories"]
                sessions = target.execute(select(metadata.tables["chat_sessions"].c.id, metadata.tables["chat_sessions"].c.document_id)).mappings()
                session_by_document = {row["document_id"]: row["id"] for row in sessions}
                legacy_rows = target.execute(select(legacy_memory_table)).mappings()
                compatible_rows = [
                    {
                        "session_id": session_by_document[row["document_id"]],
                        "compacted_through_message_id": row["compacted_through_message_id"],
                        "summary_json": row["summary_json"],
                    }
                    for row in legacy_rows
                    if row["document_id"] in session_by_document
                ]
                if compatible_rows:
                    target.execute(table.insert(), compatible_rows)
                print(f"{table_name}: {len(compatible_rows)} 条（由旧摘要回填）")
                continue

            if table_name not in source_tables:
                print(f"{table_name}: 0 条（源库无此表）")
                continue

            source_table = Table(table_name, source_metadata, autoload_with=source_engine)
            rows = [dict(row) for row in source.execute(select(source_table)).mappings()]
            compatible_rows = []
            for row in rows:
                copied = {column.name: row[column.name] for column in table.columns if column.name in row}
                if table_name == "users" and "display_name" not in copied:
                    copied["display_name"] = row["username"]
                if table_name == "documents":
                    copied.setdefault("group_id", None)
                    copied.setdefault("created_by_id", row["owner_id"])
                    copied.setdefault("last_modified_by_id", row["owner_id"])
                if table_name == "chat_messages" and "session_id" not in copied:
                    session_id = target.execute(
                        select(metadata.tables["chat_sessions"].c.id).where(
                            metadata.tables["chat_sessions"].c.document_id == row["document_id"]
                        )
                    ).scalar_one_or_none()
                    if session_id is None:
                        raise RuntimeError(f"消息 {row['id']} 找不到所属文档的初始对话")
                    copied["session_id"] = session_id
                if table_name == "agent_runs" and "session_id" not in copied:
                    session_id = target.execute(
                        select(metadata.tables["chat_messages"].c.session_id).where(
                            metadata.tables["chat_messages"].c.id == row["user_message_id"]
                        )
                    ).scalar_one_or_none()
                    if session_id is None:
                        raise RuntimeError(f"运行 {row['id']} 找不到用户消息所属对话")
                    copied["session_id"] = session_id
                compatible_rows.append(copied)
            if compatible_rows:
                target.execute(table.insert(), compatible_rows)
            print(f"{table_name}: {len(compatible_rows)} 条")

    print("SQLite -> MySQL 数据迁移完成")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"迁移失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
