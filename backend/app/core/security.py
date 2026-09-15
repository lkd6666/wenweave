"""密码哈希与 JWT 令牌的创建/校验。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt

from app.core.config import get_settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
FORCED_PASSWORD_CHANGE_VALUES = frozenset({"123456", "12345678"})


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def is_forced_password_change_value(username: str, password: str) -> bool:
    """Return whether a new password is one of the explicitly unsafe values."""
    return password in FORCED_PASSWORD_CHANGE_VALUES or password == username


def password_hash_requires_change(username: str, password_hash: str) -> bool:
    """Check a stored hash against the small set of passwords we prohibit."""
    return any(verify_password(value, password_hash) for value in (*FORCED_PASSWORD_CHANGE_VALUES, username))


def create_access_token(subject: str, extra_claims: Optional[Dict[str, Any]] = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: Dict[str, Any] = {"sub": subject, "exp": expire, "token_type": ACCESS_TOKEN_TYPE}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Create a browser-session renewal token that cannot authorize API calls."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: Dict[str, Any] = {"sub": subject, "exp": expire, "token_type": REFRESH_TOKEN_TYPE}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_scoped_token(subject: str, scope: str, extra_claims: Optional[Dict[str, Any]] = None, *, expires_in_minutes: int = 5) -> str:
    """Create a short-lived, purpose-limited token for a single browser resource."""
    settings = get_settings()
    payload: Dict[str, Any] = {
        "sub": subject,
        "scope": scope,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def decode_refresh_token(token: str) -> Dict[str, Any]:
    payload = decode_access_token(token)
    if payload.get("token_type") != REFRESH_TOKEN_TYPE:
        raise jwt.InvalidTokenError("token is not a refresh token")
    return payload
