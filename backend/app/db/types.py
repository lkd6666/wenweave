"""跨数据库字段类型。

SQLite 开发库继续使用其原生可用类型；MySQL 部署时显式升级为 BIGINT 和大文本，避免
公众号 HTML、Agent 工具参数或推理记录超过 MySQL ``TEXT`` 的 64 KiB 上限。
"""
from sqlalchemy import Integer, Text
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT, MEDIUMTEXT

# MySQL 使用 unsigned BIGINT（约 1.8e19 个主键），SQLite 则保留 INTEGER 以支持自增。
ID_TYPE = Integer().with_variant(BIGINT(unsigned=True), "mysql")

# LONGTEXT 最大约 4 GiB，用于文章 HTML 和可能包含完整 HTML 的 Agent 轨迹。
LONG_TEXT = Text().with_variant(LONGTEXT, "mysql")

# MEDIUMTEXT 最大 16 MiB，适合加密密钥与普通长配置，避免无必要的 LONGTEXT 行外存储。
MEDIUM_TEXT = Text().with_variant(MEDIUMTEXT, "mysql")
