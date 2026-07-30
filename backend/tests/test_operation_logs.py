import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import app.models  # noqa: F401
from app.api.routes.operation_logs import list_operation_logs
from app.db.base import Base
from app.models.document import Document
from app.models.operation_log import OperationLog, OperationLogStatus
from app.models.user import User, UserRole
from app.services.operation_logs import _safe_request_details, append_operation_log, classify_operation, resolve_client_ip


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
        fallback = classify_operation("PATCH", "/api/future-business-feature/42")
        self.assertEqual(theme_asset.action if theme_asset else "", "theme.reference_asset.upload")
        self.assertEqual(generation.action if generation else "", "theme.generation.save")
        self.assertEqual(link_import.action if link_import else "", "document.link_import.complete")
        self.assertEqual(fallback.action if fallback else "", "api.patch")

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
