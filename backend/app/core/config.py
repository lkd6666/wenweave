"""应用配置：统一从环境变量 / .env 文件读取，全部提供合理默认值以便本机零配置启动。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "微信公众号 AI 排版系统"

    SECRET_KEY: str = "change-this-to-a-random-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    ENCRYPTION_KEY: str = ""

    # MySQL 5.7+ / 8.0+，必须在 backend/.env 中替换用户、密码、主机和库名。
    DATABASE_URL: str = "mysql+pymysql://yibanpaiban:change-me@127.0.0.1:3306/yibanpaiban?charset=utf8mb4"

    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 单个对话 Agent 循环最大工具调用步数，避免模型陷入死循环
    CHAT_AGENT_MAX_STEPS: int = 12
    # 没有任何模型/工具流事件时的保护，以及一轮 Agent 的总运行上限。
    CHAT_AGENT_EVENT_IDLE_TIMEOUT_SECONDS: int = 300
    CHAT_AGENT_MAX_RUNTIME_SECONDS: int = 900
    CHAT_AGENT_TOOL_ARGUMENT_HEARTBEAT_SECONDS: float = 6.0
    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
