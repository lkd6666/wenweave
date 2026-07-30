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
    APP_ENV: str = "development"
    INSTANCE_ID: str = ""

    SECRET_KEY: str = "change-this-to-a-random-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    ENCRYPTION_KEY: str = ""

    # MySQL 5.7+ / 8.0+，必须在 backend/.env 中替换用户、密码、主机和库名。
    DATABASE_URL: str = "mysql+pymysql://yibanpaiban:change-me@127.0.0.1:3306/yibanpaiban?charset=utf8mb4"

    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Only these direct peers may supply a client address through X-Forwarded-For.
    TRUSTED_PROXY_CIDRS: str = ""
    DOCUMENT_SHARE_IMAGE_URL_EXPIRE_SECONDS: int = 3600

    # 没有任何模型/工具流事件时的保护，以及一轮 Agent 的总运行上限。
    # 不设工具调用步数上限：历史版本翻页等任务本就需要几十步，
    # 真正的护栏是下面的空闲超时与总运行时长。
    CHAT_AGENT_EVENT_IDLE_TIMEOUT_SECONDS: int = 300
    CHAT_AGENT_MAX_RUNTIME_SECONDS: int = 900
    CHAT_AGENT_TOOL_ARGUMENT_HEARTBEAT_SECONDS: float = 6.0
    # A single model turn is supervised by the application. Keeping these
    # limits explicit avoids an SDK retry/backoff cycle leaving the UI in a
    # misleading "running" state for several minutes.
    CHAT_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS: float = 90.0
    CHAT_AGENT_MODEL_FIRST_PROGRESS_TIMEOUT_SECONDS: float = 75.0
    CHAT_AGENT_MODEL_PROGRESS_IDLE_TIMEOUT_SECONDS: float = 60.0
    CHAT_AGENT_MODEL_STREAM_CLEANUP_GRACE_SECONDS: float = 5.0
    CHAT_AGENT_MODEL_RETRY_MAX_ATTEMPTS: int = 3
    CHAT_AGENT_MODEL_RETRY_BASE_SECONDS: float = 1.5
    CHAT_AGENT_MODEL_RETRY_MAX_DELAY_SECONDS: float = 60.0
    # 模型已结束 token 输出后的消息转换、图收尾和合规检查不应无限等待。
    CHAT_AGENT_TURN_FINALIZATION_TIMEOUT_SECONDS: float = 20.0
    CHAT_AGENT_MODEL_MESSAGE_CONVERSION_TIMEOUT_SECONDS: float = 12.0
    CHAT_AGENT_COMPLIANCE_CHECK_TIMEOUT_SECONDS: float = 12.0
    # Deprecated compatibility alias for deployments that already configured
    # the earlier single idle limit. New deployments use the two limits above.
    CHAT_AGENT_MODEL_STREAM_IDLE_TIMEOUT_SECONDS: float = 60.0
    # 向 OpenAI 兼容服务请求流式 token 用量（stream_options.include_usage）。
    # 官方 API 与主流兼容厂商都支持，用量真实值比估算更适合作压缩判据；
    # 少数自建网关会拒绝该参数，遇到时可置 false 退回估算。
    # Anthropic 侧由 SDK 默认开启，不受此开关影响。
    CHAT_AGENT_REQUEST_STREAM_USAGE: bool = True
    # Oversized tool results are kept outside the provider transcript. The
    # preview remains in the audit log indefinitely; the full payload expires.
    CHAT_TOOL_OUTPUT_RETENTION_DAYS: int = 7
    CHAT_TOOL_OUTPUT_MAX_BYTES: int = 50 * 1024 * 1024
    CHAT_TOOL_OUTPUT_CLEANUP_INTERVAL_SECONDS: int = 3600
    CHAT_AGENT_RUN_LEASE_SECONDS: int = 30
    CHAT_AGENT_RUN_EVENT_RETENTION_SECONDS: int = 3600
    CHAT_AGENT_RUN_LOCAL_EVENT_LIMIT: int = 128
    CHAT_AGENT_MAX_CONCURRENT_RUNS: int = 8
    CHAT_AGENT_MAX_CONCURRENT_RUNS_PER_USER: int = 2
    CHAT_AGENT_STARTS_PER_MINUTE: int = 12
    # A paused ask_user call does not consume an execution slot. It is
    # automatically answered with ``no_response`` after this much completely
    # inactive time so the original Agent run can finish on its own.
    CHAT_USER_QUESTION_INACTIVITY_SECONDS: int = 120
    MAX_JSON_BODY_BYTES: int = 2 * 1024 * 1024
    MAX_CHAT_MESSAGE_CHARS: int = 20_000
    MAX_DOCUMENT_HTML_BYTES: int = 10 * 1024 * 1024
    HEALTH_READINESS_TIMEOUT_SECONDS: float = 3.0
    SCHEMA_MIGRATION_LOCK_TIMEOUT_SECONDS: int = 60

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() in {"prod", "production"}

    def validate_runtime_security(self) -> None:
        """Fail fast instead of silently publishing known development secrets."""
        if not self.is_production:
            return
        errors: list[str] = []
        if self.SECRET_KEY == "change-this-to-a-random-secret-in-production" or len(self.SECRET_KEY) < 32:
            errors.append("SECRET_KEY 必须是至少 32 字符的随机生产密钥")
        if not self.ENCRYPTION_KEY:
            errors.append("生产环境必须显式配置 ENCRYPTION_KEY")
        if self.DEFAULT_ADMIN_USERNAME == "admin" and self.DEFAULT_ADMIN_PASSWORD == "admin123":
            errors.append("DEFAULT_ADMIN_USERNAME/DEFAULT_ADMIN_PASSWORD 不能使用默认凭据")
        if errors:
            raise RuntimeError("生产配置不安全：" + "；".join(errors))

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def trusted_proxy_cidrs_list(self) -> List[str]:
        return [item.strip() for item in self.TRUSTED_PROXY_CIDRS.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
