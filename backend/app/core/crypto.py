"""
对称加密工具：用于加密存储 AI Provider 的 API Key、阿里云 OSS 的 AccessKeySecret 等敏感信息。
加密密钥来源优先级：环境变量 ENCRYPTION_KEY > 本地持久化文件 data/encryption.key（自动生成）。
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import DATA_DIR, get_settings


def _load_or_create_key() -> bytes:
    settings = get_settings()
    if settings.ENCRYPTION_KEY:
        return settings.ENCRYPTION_KEY.encode("utf-8")

    key_file = DATA_DIR / "encryption.key"
    if key_file.exists():
        return key_file.read_bytes().strip()

    key = Fernet.generate_key()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    return key


@lru_cache
def _get_fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def encrypt_secret(plain_text: str) -> str:
    if not plain_text:
        return ""
    return _get_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    return _get_fernet().decrypt(cipher_text.encode("utf-8")).decode("utf-8")


def mask_secret(plain_text: str, keep: int = 4) -> str:
    """用于前端展示的脱敏版本，例如 sk-ab12************xyz9"""
    if not plain_text:
        return ""
    if len(plain_text) <= keep * 2:
        return "*" * len(plain_text)
    return f"{plain_text[:keep]}{'*' * 8}{plain_text[-keep:]}"
