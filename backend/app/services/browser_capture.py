"""Shared WeChat verification detection and short-lived browser capture sessions."""
from __future__ import annotations

import hashlib
import hmac
import html
import re
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.layout_capture_session import LayoutCaptureSession


CAPTURE_PURPOSE_LAYOUT_REFERENCE = "layout_reference"
CAPTURE_PURPOSE_WEB_ARTICLE_IMPORT = "web_article_import"
CAPTURE_PURPOSES = {CAPTURE_PURPOSE_LAYOUT_REFERENCE, CAPTURE_PURPOSE_WEB_ARTICLE_IMPORT}
CAPTURE_SESSION_TTL = timedelta(minutes=10)
MAX_CAPTURE_HTML_BYTES = 5 * 1024 * 1024
# Count is deliberately higher than the legacy 50-image ceiling.  Byte limits
# still bound memory, storage, and upload cost for image-heavy articles.
MAX_CAPTURE_ASSETS = 200
MAX_CAPTURE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_CAPTURE_IMAGE_TOTAL_BYTES = 50 * 1024 * 1024
WECHAT_HOST = "mp.weixin.qq.com"
_WECHAT_CONTENT_RE = re.compile(r"\bid\s*=\s*(['\"])js_content\1", re.IGNORECASE)


class BrowserCaptureError(ValueError):
    pass


class BrowserCaptureExpiredError(BrowserCaptureError):
    pass


class WechatVerificationRequiredError(BrowserCaptureError):
    def __init__(self, canonical_url: str) -> None:
        super().__init__("微信要求在浏览器中完成验证后再抓取文章")
        self.canonical_url = canonical_url


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_wechat_article_url(raw_url: str) -> str | None:
    try:
        parsed = urlsplit(raw_url.strip())
        if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
            return None
        if parsed.port not in {None, 443}:
            return None
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if host != WECHAT_HOST or not (parsed.path == "/s" or parsed.path.startswith("/s/")):
        return None
    return urlunsplit(("https", WECHAT_HOST, parsed.path or "/", parsed.query, ""))


def resolve_wechat_capture_url(verification_url: str, requested_url: str = "") -> str | None:
    requested_article = normalize_wechat_article_url(requested_url)
    if requested_article:
        return requested_article
    direct_article = normalize_wechat_article_url(verification_url)
    if direct_article:
        return direct_article
    try:
        parsed = urlsplit(verification_url.strip())
        if parsed.scheme.lower() != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
            return None
        query = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if host != WECHAT_HOST or parsed.path != "/mp/wappoc_appmsgcaptcha":
        return None
    targets = query.get("target_url", [])
    return normalize_wechat_article_url(targets[0]) if len(targets) == 1 else None


def is_wechat_verification_page(source: str, canonical_url: str) -> bool:
    host = (urlsplit(canonical_url).hostname or "").lower().rstrip(".")
    if host != WECHAT_HOST or _WECHAT_CONTENT_RE.search(source):
        return False
    visible_text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", source))).strip()
    return bool(
        ("环境异常" in visible_text and ("验证" in visible_text or "继续访问" in visible_text))
        or "访问过于频繁" in visible_text
        or "完成验证后即可继续访问" in visible_text
    )


def create_browser_capture_session(
    raw_url: str,
    user_id: int,
    purpose: str,
    db: Session,
) -> tuple[LayoutCaptureSession, str]:
    canonical_url = resolve_wechat_capture_url(raw_url)
    if canonical_url is None:
        raise BrowserCaptureError("浏览器抓取首版仅支持微信公众号文章")
    if purpose not in CAPTURE_PURPOSES:
        raise BrowserCaptureError("浏览器采集用途无效")
    token = token_urlsafe(32)
    capture_session = LayoutCaptureSession(
        id=str(uuid4()),
        user_id=user_id,
        canonical_url=canonical_url,
        purpose=purpose,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        status="pending",
        expires_at=_utcnow() + CAPTURE_SESSION_TTL,
    )
    db.add(capture_session)
    db.flush()
    return capture_session, token


def load_browser_capture_session(
    db: Session,
    capture_id: str,
    capture_token: str,
    captured_url: str,
    purpose: str,
) -> LayoutCaptureSession:
    capture_session = (
        db.query(LayoutCaptureSession)
        .filter(LayoutCaptureSession.id == capture_id)
        .with_for_update()
        .one_or_none()
    )
    supplied_hash = hashlib.sha256(capture_token.encode("utf-8")).hexdigest()
    if capture_session is None or not hmac.compare_digest(capture_session.token_hash, supplied_hash):
        raise BrowserCaptureExpiredError("浏览器采集会话不存在或令牌无效")
    if capture_session.purpose != purpose:
        raise BrowserCaptureExpiredError("浏览器采集会话用途不匹配，请重新发起抓取")
    if capture_session.status != "pending":
        raise BrowserCaptureExpiredError("浏览器采集会话已使用，请重新发起抓取")
    if _as_utc(capture_session.expires_at) <= _utcnow():
        raise BrowserCaptureExpiredError("浏览器采集会话已过期，请重新发起抓取")
    normalized_url = normalize_wechat_article_url(captured_url)
    if normalized_url is None or normalized_url != capture_session.canonical_url:
        raise BrowserCaptureError("浏览器当前文章与待采集链接不一致")
    return capture_session


def complete_browser_capture_session(capture_session: LayoutCaptureSession) -> None:
    capture_session.status = "completed"
    capture_session.consumed_at = _utcnow()


def cleanup_expired_browser_capture_sessions(db: Session, now: datetime | None = None) -> int:
    expired_ids = [
        session_id
        for (session_id,) in (
            db.query(LayoutCaptureSession.id)
            .filter(LayoutCaptureSession.expires_at <= (now or _utcnow()))
            .order_by(LayoutCaptureSession.expires_at, LayoutCaptureSession.id)
            .limit(500)
            .all()
        )
    ]
    if not expired_ids:
        return 0
    deleted = (
        db.query(LayoutCaptureSession)
        .filter(LayoutCaptureSession.id.in_(expired_ids))
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()
    return int(deleted)
