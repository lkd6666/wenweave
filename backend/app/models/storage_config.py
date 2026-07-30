from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import ID_TYPE, MEDIUM_TEXT


class StorageConfig(Base):
    """对象存储配置，全局单条记录（id 固定为 1）。"""

    __tablename__ = "storage_configs"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    bucket: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    access_key_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    access_key_secret_encrypted: Mapped[str] = mapped_column(MEDIUM_TEXT, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="aliyun_oss")
    region_or_zone: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    upload_endpoint: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    custom_domain: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
