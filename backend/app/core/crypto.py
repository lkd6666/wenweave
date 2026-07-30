"""
对称加密工具：用于加密存储 AI Provider 的 API Key、阿里云 OSS 的 AccessKeySecret 等敏感信息。
加密密钥来源优先级：环境变量 ENCRYPTION_KEY > 本地持久化文件 data/encryption.key（自动生成）。
"""
from __future__ import annotations

import os
import time
from functools import lru_cache
from uuid import uuid4

from cryptography.fernet import Fernet

from app.core.config import DATA_DIR, get_settings


def _load_or_create_key() -> bytes:
    settings = get_settings()
    if settings.ENCRYPTION_KEY:
        return settings.ENCRYPTION_KEY.encode("utf-8")

    key_file = DATA_DIR / "encryption.key"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = key_file.read_bytes().strip() if key_file.exists() else b""
    if existing:
        return existing

    # A direct ``write_bytes`` leaves a window where two workers cache
    # different keys.  Serialize first creation with an exclusive sidecar and
    # publish the completed key by atomic replacement.
    lock_file = key_file.with_suffix(".key.lock")
    deadline = time.monotonic() + 10.0
    while True:
        try:
            descriptor = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = key_file.read_bytes().strip() if key_file.exists() else b""
            if existing:
                return existing
            if time.monotonic() >= deadline:
                raise RuntimeError("等待本地 encryption.key 初始化超时；请改用显式 ENCRYPTION_KEY")
            time.sleep(0.05)
            continue
        break

    try:
        existing = key_file.read_bytes().strip() if key_file.exists() else b""
        if existing:
            return existing
        key = Fernet.generate_key()
        temporary = key_file.with_name(f"{key_file.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, key_file)
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return key
    finally:
        os.close(descriptor)
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


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
