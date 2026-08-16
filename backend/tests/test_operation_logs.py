import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import app.models  # noqa: F401
from app.api.routes.operation_logs import list_operation_logs
from app.db.base import Base
from app.models.document import Document
from app.models.operation_log import OperationLog, OperationLogStatus
from app.models.user import User, UserRole
from app.core.security import create_refresh_token
from app.services.operation_logs import (
    _safe_request_details,
    append_operation_log,
    capture_request_context,
    classify_operation,
    resolve_client_ip,
    set_request_audit_actor,
    with_request_audit_actor,
)


class OperationLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            username="auditor",
            display_name="审计用户",
            password_hash="not-used",
            role=UserRole.ADMIN,
            is_active=True,
        )
        self.db.add(self.user)
        self.db.flush()
        self.document = Document(owner_id=self.user.id, title="审计文档", current_html="<p>正文</p>")
        self.db.add(self.document)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_append_keeps_snapshots_and_redacts_sensitive_details(self) -> None:
        append_operation_log(
            self.db,
            actor=self.user,
            action="document.content.update",
            resource_type="document",
            resource_id=self.document.id,
            resource_name=self.document.title,
            document_id=self.document.id,
            details={
                "mode": "manual",
                "message": "不得保存的正文",
                "nested": {"api_key": "不得保存", "version": 3},
            },
            request_id="request-1",
            client_ip="2001:db8::1",
            user_agent="audit-test/1.0",
        )
        self.db.commit()

        item = self.db.query(OperationLog).one()
        details = json.loads(item.details_json)
        self.assertEqual(item.actor_username, "auditor")
        self.assertEqual(item.actor_display_name, "审计用户")
        self.assertEqual(item.resource_name, "审计文档")
        self.assertEqual(details, {"mode": "manual", "nested": {"version": 3}})
        self.assertNotIn("正文", item.details_json)
        self.assertNotIn("api_key", item.details_json)
        self.assertEqual(item.client_ip, "2001:db8::1")
        self.assertEqual(item.user_agent, "audit-test/1.0")

    def test_list_filters_by_status_and_document(self) -> None:
        append_operation_log(
            self.db,
            actor=self.user,
            action="document.content.update",
            resource_type="document",
            resource_id=self.document.id,
            resource_name=self.document.title,
            document_id=self.document.id,
            status=OperationLogStatus.SUCCEEDED,
        )
        append_operation_log(
            self.db,
            actor=self.user,
            action="chat.run",
            resource_type="chat_run",
            resource_id="run-1",
            document_id=self.document.id,
            status=OperationLogStatus.FAILED,
            client_ip="203.0.113.4",
        )
        self.db.commit()

        result = list_operation_logs(
            page=1,
            page_size=30,
            actor_user_id=None,
            action=None,
            resource_type=None,
            document_id=self.document.id,
            status=OperationLogStatus.FAILED,
            client_ip=None,
            started_at=None,
            ended_at=None,
            keyword=None,
            db=self.db,
        )
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].action, "chat.run")
        self.assertEqual(result.items[0].status, OperationLogStatus.FAILED)

    def test_deferred_routes_only_record_middleware_failures(self) -> None:
        for path in (
            f"/api/documents/{self.document.id}/chat",
            f"/api/documents/{self.document.id}/wechat-drafts",
            f"/api/documents/{self.document.id}/wechat-drafts/stream",
            f"/api/documents/{self.document.id}/chat-runs/run-1/cancel",
        ):
            route = classify_operation("POST", path)
            self.assertIsNotNone(route)
            assert route is not None
            self.assertTrue(route.deferred_terminal)
        item = classify_operation("PATCH", f"/api/documents/{self.document.id}/content")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.action, "document.content.update")
        self.assertEqual(item.document_id, self.document.id)

    def test_classifies_document_share_mutations(self) -> None:
        created = classify_operation("POST", f"/api/documents/{self.document.id}/shares")
        updated = classify_operation("PATCH", f"/api/documents/{self.document.id}/shares/42")
        revoked = classify_operation("POST", f"/api/documents/{self.document.id}/shares/42/revoke")
        self.assertEqual(created.action if created else "", "document.share.create")
        self.assertEqual(updated.action if updated else "", "document.share.update")
        self.assertEqual(revoked.action if revoked else "", "document.share.revoke")

    def test_classifies_theme_and_link_import_mutations_with_fallback(self) -> None:
        theme_asset = classify_operation("POST", "/api/gzh-theme-assets")
        generation = classify_operation("POST", "/api/gzh-theme-generations/job-1/save")
        link_import = classify_operation("POST", "/api/documents/link-imports/import-1/complete")
        capture_create = classify_operation("POST", "/api/documents/link-imports/capture-sessions")
        capture_complete = classify_operation(
            "POST",
            "/api/documents/link-imports/capture-sessions/capture-1/complete",
        )
        fallback = classify_operation("PATCH", "/api/future-business-feature/42")
        self.assertEqual(theme_asset.action if theme_asset else "", "theme.reference_asset.upload")
        self.assertEqual(generation.action if generation else "", "theme.generation.save")
        self.assertEqual(link_import.action if link_import else "", "document.link_import.complete")
        self.assertEqual(capture_create.action if capture_create else "", "document.link_import.capture.create")
        self.assertEqual(capture_complete.action if capture_complete else "", "document.link_import.capture.complete")
        self.assertEqual(capture_complete.resource_id if capture_complete else "", "capture-1")
        self.assertEqual(fallback.action if fallback else "", "api.patch")

    def test_classifies_auth_refresh_as_account_operation(self) -> None:
        route = classify_operation("POST", "/api/auth/refresh")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertEqual(route.action, "auth.refresh")
        self.assertEqual(route.resource_type, "account")

    def test_refresh_request_records_cookie_user_as_actor(self) -> None:
        user = SimpleNamespace(id=17, username="refresh-user", display_name="刷新用户", is_active=True)
        db = SimpleNamespace(get=lambda _model, user_id: user if user_id == user.id else None, close=lambda: None)
        refresh_token = create_refresh_token(str(user.id))
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/auth/refresh",
                "headers": [(b"cookie", f"refresh_token={refresh_token}".encode())],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            }
        )

        with patch("app.services.operation_logs.SessionLocal", return_value=db):
            context = asyncio.run(capture_request_context(request))

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.actor_user_id, user.id)
        self.assertEqual(context.actor_username, user.username)
        self.assertEqual(context.actor_display_name, user.display_name)

    def test_only_typed_server_actor_override_can_attribute_anonymous_request(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "https",
                "path": "/api/documents/link-imports/capture-sessions/capture-1/complete",
                "headers": [(b"x-user-id", str(self.user.id).encode())],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 443),
            }
        )
        context = asyncio.run(capture_request_context(request))
        self.assertIsNotNone(context)
        assert context is not None
        self.assertIsNone(context.actor_user_id)

        request.state.operation_audit_actor = {
            "user_id": self.user.id,
            "username": self.user.username,
            "display_name": self.user.display_name,
        }
        self.assertIsNone(with_request_audit_actor(context, request).actor_user_id)

        set_request_audit_actor(request, self.user)
        attributed = with_request_audit_actor(context, request)
        self.assertEqual(attributed.actor_user_id, self.user.id)
        self.assertEqual(attributed.actor_username, self.user.username)
        self.assertEqual(attributed.actor_display_name, self.user.display_name)

    def test_resolves_real_ip_only_for_trusted_proxy(self) -> None:
        def request(peer: str, headers: dict[str, str]) -> Request:
            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/api/documents",
                    "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
                    "client": (peer, 443),
                    "server": ("testserver", 80),
                }
            )

        trusted = request("10.0.0.10", {"x-forwarded-for": "198.51.100.8, 10.0.0.7"})
        untrusted = request("203.0.113.9", {"x-forwarded-for": "198.51.100.8"})
        cloudflare = request("10.0.0.10", {"cf-connecting-ip": "2001:db8::8"})
        cidrs = ["10.0.0.0/8"]
        self.assertEqual(resolve_client_ip(trusted, cidrs), "198.51.100.8")
        self.assertEqual(resolve_client_ip(untrusted, cidrs), "203.0.113.9")
        self.assertEqual(resolve_client_ip(cloudflare, cidrs), "2001:db8::8")

    def test_resolves_client_ip_through_cdn_waf_and_nginx(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/documents",
                "headers": [
                    (b"x-forwarded-for", b"203.0.113.42, 198.51.100.37, 172.18.0.5"),
                ],
                # Uvicorn receives the request from the local Nginx proxy.
                "client": ("127.0.0.1", 8001),
                "server": ("testserver", 80),
            }
        )

        self.assertEqual(
            resolve_client_ip(
                request,
                ["127.0.0.1/32", "172.18.0.0/16", "198.51.100.0/24"],
            ),
            "203.0.113.42",
        )

    def test_login_form_extracts_only_username(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/auth/login",
                "headers": [
                    (b"content-type", b"application/x-www-form-urlencoded"),
                    (b"content-length", b"34"),
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            }
        )
        request._body = b"username=alice&password=not-recorded"
        details = _safe_request_details(request)
        self.assertEqual(details, {"username": "alice"})
        self.assertNotIn("password", details)
