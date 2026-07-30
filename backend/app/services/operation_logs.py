"""Shared, privacy-safe operation auditing helpers."""
from __future__ import annotations

import ipaddress
import json
import logging
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Any, Iterable
from urllib.parse import parse_qs

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.gzh_theme import GzhTheme
from app.models.operation_log import OperationLog, OperationLogStatus
from app.models.template_library import TemplateCategory, TemplateLibraryItem
from app.models.user import User
from app.models.user_group import UserGroup
from app.models.wechat_account import WeChatAccount


logger = logging.getLogger(__name__)

_operation_request_id: ContextVar[str] = ContextVar("operation_request_id", default="")

MAX_DETAIL_LENGTH = 256
MAX_SUMMARY_LENGTH = 1024
MAX_CLIENT_IP_LENGTH = 45
MAX_USER_AGENT_LENGTH = 512
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "api_key", "html", "prompt", "message", "content")


@dataclass(frozen=True)
class AuditRoute:
    action: str
    resource_type: str
    document_id: int | None = None
    session_id: int | None = None
    resource_id: str = ""
    deferred_terminal: bool = False


@dataclass(frozen=True)
class OperationRequestMetadata:
    client_ip: str = ""
    user_agent: str = ""


@dataclass(frozen=True)
class AuditRequestContext:
    route: AuditRoute
    actor_user_id: int | None
    actor_username: str
    actor_display_name: str
    resource_name: str
    request_id: str
    details: dict[str, Any]
    client_ip: str
    user_agent: str


_operation_request_metadata: ContextVar[OperationRequestMetadata] = ContextVar(
    "operation_request_metadata", default=OperationRequestMetadata()
)


def _normal_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _document_id(path: str) -> int | None:
    match = re.match(r"^/api/documents/(\d+)(?:/|$)", path)
    return int(match.group(1)) if match else None


def _session_id(path: str) -> int | None:
    match = re.search(r"/chat-sessions/(\d+)(?:/|$)", path)
    return int(match.group(1)) if match else None


def _parse_ip(value: str | None) -> str:
    candidate = str(value or "").strip().strip('"')
    if not candidate or candidate.lower() == "unknown" or candidate.startswith("_"):
        return ""
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    elif candidate.count(":") == 1:
        host, port = candidate.rsplit(":", 1)
        if port.isdigit():
            candidate = host
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return ""
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return str(parsed.ipv4_mapped)
    return str(parsed)


def _trusted_proxy_networks(cidrs: Iterable[str] | None = None) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in cidrs if cidrs is not None else get_settings().trusted_proxy_cidrs_list:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXY_CIDRS entry: %s", cidr)
    return tuple(networks)


def _is_trusted_proxy(address: str, networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed.version == network.version and parsed in network for network in networks)


def _forwarded_addresses(value: str) -> list[str]:
    addresses: list[str] = []
    for entry in value.split(","):
        for parameter in entry.split(";"):
            key, separator, raw_value = parameter.strip().partition("=")
            if separator and key.lower() == "for":
                parsed = _parse_ip(raw_value)
                if parsed:
                    addresses.append(parsed)
    return addresses


def _proxy_chain_client(
    addresses: list[str], peer: str, networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]
) -> str:
    for address in reversed([*addresses, peer]):
        if not _is_trusted_proxy(address, networks):
            return address
    return addresses[0] if addresses else peer


def resolve_client_ip(request: Request, trusted_proxy_cidrs: Iterable[str] | None = None) -> str:
    """Resolve the user IP without trusting client-supplied proxy headers.

    Forwarded headers are considered only when the direct TCP peer belongs to
    ``TRUSTED_PROXY_CIDRS``. The proxy chain is traversed right-to-left so an
    attacker-provided left-most X-Forwarded-For value cannot override the
    address appended by a trusted reverse proxy.
    """
    peer = _parse_ip(request.client.host if request.client else "")
    if not peer:
        return ""
    networks = _trusted_proxy_networks(trusted_proxy_cidrs)
    if not networks or not _is_trusted_proxy(peer, networks):
        return peer

    for header in ("cf-connecting-ip", "true-client-ip"):
        candidate = _parse_ip(request.headers.get(header))
        if candidate:
            return candidate

    forwarded = _forwarded_addresses(request.headers.get("forwarded", ""))
    if forwarded:
        return _proxy_chain_client(forwarded, peer, networks)
    forwarded_for = [_parse_ip(item) for item in request.headers.get("x-forwarded-for", "").split(",")]
    forwarded_for = [item for item in forwarded_for if item]
    return _proxy_chain_client(forwarded_for, peer, networks)


def request_metadata(request: Request) -> OperationRequestMetadata:
    user_agent = re.sub(r"\s+", " ", request.headers.get("user-agent", "")).strip()
    return OperationRequestMetadata(
        client_ip=resolve_client_ip(request),
        user_agent=_safe_text(user_agent, MAX_USER_AGENT_LENGTH),
    )


def classify_operation(method: str, raw_path: str) -> AuditRoute | None:
    """Translate mutating routes into stable audit action codes.

    The fallback intentionally covers newly-added business mutation endpoints,
    while known read-only POST helpers are excluded below.
    """
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    path = _normal_path(raw_path)
    if path in {"/api/compliance/check", "/api/layout-references/preview"} or path.endswith("/chat-context/preview"):
        return None
    document_id = _document_id(path)
    session_id = _session_id(path)
    # These operations persist one final result themselves. The middleware
    # records only their rejected/failed requests so a 4xx is not invisible.
    if document_id is not None and re.match(r"^/api/documents/\d+/chat$", path):
        return AuditRoute("chat.run", "chat_run", document_id, resource_id=str(document_id), deferred_terminal=True)
    if document_id is not None and re.match(r"^/api/documents/\d+/wechat-drafts(?:/stream)?$", path):
        return AuditRoute("wechat.draft.push", "wechat_draft", document_id, resource_id=str(document_id), deferred_terminal=True)
    if document_id is not None and re.match(r"^/api/documents/\d+/chat-runs/[^/]+/cancel$", path):
        run_id = path.split("/")[-2]
        return AuditRoute("chat.run.cancel_request", "chat_run", document_id, resource_id=run_id, deferred_terminal=True)
    if path == "/api/auth/login":
        return AuditRoute("auth.login", "account")
    if path == "/api/documents":
        return AuditRoute("document.create", "document")
    if path.startswith("/api/documents/link-imports"):
        path_parts = path.strip("/").split("/")
        resource_id = path_parts[3] if len(path_parts) > 3 else ""
        if path.endswith("/preview"):
            return AuditRoute("document.link_import.preview", "document_import")
        if path.endswith("/complete"):
            return AuditRoute("document.link_import.complete", "document_import", resource_id=resource_id)
        return AuditRoute(
            "document.link_import.delete" if method == "DELETE" else "document.link_import.create",
            "document_import",
            resource_id=resource_id,
        )
    if path.startswith("/api/documents/imports"):
        action = "document.import.complete" if path.endswith("/complete") else "document.import.upload"
        return AuditRoute(action, "document_import", resource_id=path.rsplit("/", 1)[-1])
    if document_id is not None:
        if path.endswith("/shares"):
            action = "document.share.create"
        elif "/shares/" in path and path.endswith("/revoke"):
            action = "document.share.revoke"
        elif "/shares/" in path:
            action = "document.share.update"
        elif path.endswith("/content"):
            action = "document.content.update"
        elif path.endswith("/images"):
            action = "document.image.upload"
        elif path.endswith("/wechat-cover"):
            action = "document.wechat_cover.upload"
        elif path.endswith("/revert-last-ai-change"):
            action = "document.ai.revert"
        elif path.endswith("/revert-to-message"):
            action = "document.message.restore"
        elif "/versions/" in path and path.endswith("/restore"):
            action = "document.version.restore"
        elif "/versions/" in path and path.endswith("/copy"):
            action = "document.version.copy"
        elif "/chat-images" in path:
            action = "chat.image.delete" if method == "DELETE" else "chat.image.upload"
        elif "/chat-sessions/" in path:
            suffix = path.rsplit("/", 1)[-1]
            action = {
                "archive": "chat.session.archive",
                "restore": "chat.session.restore",
                "truncate": "chat.context.truncate",
                "restore-context": "chat.context.restore",
                "layout-reference": "chat.layout_reference.clear",
            }.get(suffix, "chat.session.update" if method == "PATCH" else "chat.session.create")
        elif path.endswith("/chat-sessions"):
            action = "chat.session.create"
        elif "/chat-context/compact" in path:
            action = "chat.context.compact"
        elif "/chat-runs/" in path and path.endswith("/cancel"):
            action = "chat.run.cancel_request"
        elif "/gzh-theme-proposals" in path:
            action = "theme.proposal.approve" if path.endswith("/approve") else "theme.proposal.create"
        elif method == "DELETE":
            action = "document.delete"
        elif method == "PATCH":
            action = "document.update"
        else:
            action = "document.update"
        return AuditRoute(action, "chat_session" if session_id else "document", document_id, session_id, str(session_id or document_id))

    if path == "/api/gzh-theme-assets":
        return AuditRoute("theme.reference_asset.upload", "theme_reference_asset")
    if path.startswith("/api/gzh-theme-generations"):
        resource_id = path.split("/")[3] if path.count("/") >= 3 else ""
        suffix = path.rsplit("/", 1)[-1]
        action = "theme.generation.create" if path == "/api/gzh-theme-generations" else {
            "cancel": "theme.generation.cancel",
            "save": "theme.generation.save",
        }.get(suffix, "theme.generation.update")
        return AuditRoute(action, "theme_generation", resource_id=resource_id)
    if path.startswith("/api/gzh-theme-versions"):
        resource_id = path.split("/")[3] if path.count("/") >= 3 else ""
        return AuditRoute("theme.version.publish" if path.endswith("/publish") else "theme.version.update", "theme_version", resource_id=resource_id)

    if path.startswith("/api/ai-providers/models/"):
        resource_id = path.rsplit("/", 1)[-1]
        verb = "delete" if method == "DELETE" else "update"
        return AuditRoute(f"ai_model.{verb}", "ai_model", resource_id=resource_id)
    if re.match(r"^/api/ai-providers/\d+/models(?:/bulk)?$", path):
        provider_id = path.split("/")[3]
        return AuditRoute("ai_model.bulk_create" if path.endswith("/bulk") else "ai_model.create", "ai_provider", resource_id=provider_id)

    if path == "/api/branding":
        return AuditRoute("branding.update", "branding")
    if path in {"/api/branding/logo", "/api/branding/favicon"}:
        asset = path.rsplit("/", 1)[-1]
        return AuditRoute(f"branding.{asset}.upload", "branding", resource_id=asset)
    if path in {"/api/branding/assets/logo", "/api/branding/assets/favicon"}:
        asset = path.rsplit("/", 1)[-1]
        return AuditRoute(f"branding.{asset}.delete", "branding", resource_id=asset)

    mappings = (
        ("/api/document-groups", "document_group"),
        ("/api/users", "user"),
        ("/api/user-groups", "user_group"),
        ("/api/wechat-accounts", "wechat_account"),
        ("/api/ai-providers", "ai_provider"),
        ("/api/storage", "storage"),
        ("/api/gzh-themes", "theme"),
        ("/api/gzh-theme", "theme"),
        ("/api/template-library", "template"),
    )
    for prefix, resource_type in mappings:
        if path == prefix or path.startswith(prefix + "/"):
            verb = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}[method]
            if path.endswith("/test"):
                verb = "test"
            elif path.endswith("/discover-models"):
                verb = "discover"
            elif path.endswith("/publish"):
                verb = "publish"
            elif path.endswith("/archive"):
                verb = "archive"
            elif path.endswith("/cancel"):
                verb = "cancel"
            resource_id = path.rsplit("/", 1)[-1] if path != prefix else ""
            if resource_type == "user" and path.endswith("/change-password"):
                return AuditRoute("account.password.change", "account")
            return AuditRoute(f"{resource_type}.{verb}", resource_type, resource_id=resource_id)
    # Do not allow future business mutation routes to silently skip auditing.
    # Read-only POST helpers must be explicitly added to the exclusions above.
    return AuditRoute(f"api.{method.lower()}", "api_route", resource_id=path)


def _safe_text(value: object, limit: int = MAX_DETAIL_LENGTH) -> str:
    text = str(value or "").strip()
    return text[:limit]


def sanitize_details(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
                continue
            result[str(key)[:64]] = sanitize_details(item)
        return result
    if isinstance(value, list):
        return [sanitize_details(item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _safe_text(value) if isinstance(value, str) else value
    return _safe_text(value)


def _safe_request_details(request: Request) -> dict[str, Any]:
    """Use only short, explicit metadata fields; never retain request bodies."""
    content_type = request.headers.get("content-type", "").lower()
    content_length = request.headers.get("content-length", "0")
    try:
        if (
            "application/json" not in content_type
            and "application/x-www-form-urlencoded" not in content_type
        ) or int(content_length or 0) > 64 * 1024:
            return {}
    except ValueError:
        return {}
    raw_body = request._body if hasattr(request, "_body") else b""
    try:
        if "application/x-www-form-urlencoded" in content_type:
            payload = {key: values[0] for key, values in parse_qs(raw_body.decode("utf-8")).items() if values}
        else:
            payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    allowed = ("title", "name", "system_name", "username", "display_name", "filename", "model_name", "app_id", "sync_mode")
    return {key: _safe_text(payload[key]) for key in allowed if payload.get(key) not in (None, "")}


def _actor_snapshot(authorization: str) -> tuple[int | None, str, str]:
    if not authorization.startswith("Bearer "):
        return None, "", ""
    try:
        payload = decode_access_token(authorization[7:].strip())
        user_id = int(payload.get("sub"))
    except Exception:  # noqa: BLE001 - invalid credentials must never break a request audit.
        return None, "", ""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return None, "", ""
        return user.id, user.username, user.display_name
    finally:
        db.close()


def _target_snapshot(route: AuditRoute) -> str:
    if not route.resource_id:
        return ""
    try:
        numeric_id = int(route.resource_id)
    except ValueError:
        return ""
    model_by_type = {
        "document": (Document, "title"),
        "chat_session": (ChatSession, "title"),
        "document_group": (DocumentGroup, "name"),
        "user": (User, "username"),
        "user_group": (UserGroup, "name"),
        "wechat_account": (WeChatAccount, "name"),
        "ai_provider": (AIProvider, "name"),
        "ai_model": (AIModel, "display_name"),
        "template": (TemplateLibraryItem, "name"),
        "template_category": (TemplateCategory, "name"),
        "theme": (GzhTheme, "name"),
    }
    entry = model_by_type.get(route.resource_type)
    if not entry:
        return ""
    db = SessionLocal()
    try:
        target = db.get(entry[0], numeric_id)
        return _safe_text(getattr(target, entry[1], ""), 256) if target else ""
    except Exception:  # noqa: BLE001
        logger.exception("operation_log_snapshot_failed resource=%s", route.resource_type)
        return ""
    finally:
        db.close()


def _login_actor_snapshot(username: str) -> tuple[int | None, str, str]:
    if not username:
        return None, "", ""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return None, username, ""
        return user.id, user.username, user.display_name
    finally:
        db.close()


async def capture_request_context(
    request: Request, metadata: OperationRequestMetadata | None = None
) -> AuditRequestContext | None:
    route = classify_operation(request.method, request.url.path)
    if not route:
        return None
    # Starlette caches request.body(), so downstream FastAPI validation can read it normally.
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("application/json") or content_type.startswith("application/x-www-form-urlencoded"):
        try:
            await request.body()
        except Exception:  # noqa: BLE001
            pass
    details = _safe_request_details(request)
    actor_user_id, actor_username, actor_display_name = _actor_snapshot(request.headers.get("authorization", ""))
    if route.action == "auth.login":
        actor_user_id, actor_username, actor_display_name = _login_actor_snapshot(str(details.get("username", "")))
    resource_name = _target_snapshot(route)
    if not resource_name:
        resource_name = _safe_text(
            details.get("title") or details.get("name") or details.get("display_name") or details.get("username")
        )
    metadata = metadata or request_metadata(request)
    return AuditRequestContext(
        route=route,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        actor_display_name=actor_display_name,
        resource_name=resource_name,
        request_id=str(getattr(request.state, "request_id", "") or request.headers.get("x-request-id", ""))[:128],
        details=details,
        client_ip=metadata.client_ip,
        user_agent=metadata.user_agent,
    )


def append_operation_log(
    db: Session,
    *,
    actor: User | None,
    action: str,
    resource_type: str,
    resource_id: str | int = "",
    resource_name: str = "",
    document_id: int | None = None,
    session_id: int | None = None,
    status: OperationLogStatus = OperationLogStatus.SUCCEEDED,
    summary: str = "",
    error_summary: str = "",
    details: dict[str, Any] | None = None,
    request_id: str = "",
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> OperationLog:
    metadata = get_operation_request_metadata()
    item = OperationLog(
        actor_user_id=actor.id if actor else None,
        actor_username=_safe_text(actor.username if actor else "", 64),
        actor_display_name=_safe_text(actor.display_name if actor else "", 64),
        action=action[:128],
        resource_type=resource_type[:64],
        resource_id=_safe_text(resource_id, 128),
        resource_name=_safe_text(resource_name, 256),
        document_id=document_id,
        session_id=session_id,
        status=status,
        summary=_safe_text(summary, MAX_SUMMARY_LENGTH),
        error_summary=_safe_text(error_summary, MAX_SUMMARY_LENGTH),
        details_json=json.dumps(sanitize_details(details or {}), ensure_ascii=False, separators=(",", ":")),
        request_id=_safe_text(request_id, 128),
        client_ip=_safe_text(metadata.client_ip if client_ip is None else client_ip, MAX_CLIENT_IP_LENGTH),
        user_agent=_safe_text(metadata.user_agent if user_agent is None else user_agent, MAX_USER_AGENT_LENGTH),
    )
    db.add(item)
    return item


def persist_request_audit(context: AuditRequestContext, response_status: int, *, exception: bool = False) -> None:
    success = 200 <= response_status < 400
    is_server_failure = response_status >= 500 or exception
    status = OperationLogStatus.SUCCEEDED if success else OperationLogStatus.FAILED
    summary = "操作完成" if success else f"操作失败（HTTP {response_status}）"
    if context.route.action == "auth.login":
        summary = "登录成功" if success else "登录失败"
    db = SessionLocal()
    try:
        log = OperationLog(
            actor_user_id=context.actor_user_id,
            actor_username=context.actor_username,
            actor_display_name=context.actor_display_name,
            action=context.route.action,
            resource_type=context.route.resource_type,
            resource_id=context.route.resource_id,
            resource_name=context.resource_name,
            document_id=context.route.document_id,
            session_id=context.route.session_id,
            status=status,
            summary=summary,
            error_summary="服务器处理失败" if is_server_failure else "",
            details_json=json.dumps(sanitize_details(context.details), ensure_ascii=False, separators=(",", ":")),
            request_id=context.request_id,
            client_ip=context.client_ip,
            user_agent=context.user_agent,
        )
        db.add(log)
        db.commit()
    except Exception:  # noqa: BLE001 - auditing must not turn a success into a 500.
        db.rollback()
        logger.exception("operation_log_persist_failed action=%s", context.route.action)
    finally:
        db.close()


def with_request_id(context: AuditRequestContext, request_id: str) -> AuditRequestContext:
    return replace(context, request_id=_safe_text(request_id, 128)) if request_id else context


def set_operation_request_id(request_id: str) -> Token[str]:
    return _operation_request_id.set(_safe_text(request_id, 128))


def reset_operation_request_id(token: Token[str]) -> None:
    _operation_request_id.reset(token)


def get_operation_request_id() -> str:
    return _operation_request_id.get()


def set_operation_request_metadata(metadata: OperationRequestMetadata) -> Token[OperationRequestMetadata]:
    return _operation_request_metadata.set(metadata)


def reset_operation_request_metadata(token: Token[OperationRequestMetadata]) -> None:
    _operation_request_metadata.reset(token)


def get_operation_request_metadata() -> OperationRequestMetadata:
    return _operation_request_metadata.get()
