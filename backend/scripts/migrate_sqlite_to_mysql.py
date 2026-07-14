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
    "ai_providers",
    "ai_models",
    "storage_configs",
    "document_groups",
    "documents",
    "chat_messages",
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
