import unittest
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import app.models  # noqa: F401
from app.api.routes import document_shares
from app.db.base import Base
from app.models.document import Document
from app.models.document_share import DocumentShare, DocumentShareVisit
from app.models.document_visibility import VisibilityMode
from app.models.user import User, UserRole
from app.services.document_shares import (
    create_share,
    document_revision,
    record_public_visit,
    revoke_document_shares,
    revoke_share,
    request_ip_address,
    token_hash,
    utcnow,
)


def make_request(
    *,
    ip: str = "203.0.113.7",
    user_agent: str = "ShareTest/1.0",
    referer: str = "https://example.test/",
    forwarded_for: str = "",
) -> Request:
    headers = [(b"user-agent", user_agent.encode()), (b"referer", referer.encode())]
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/public/shares/test",
            "headers": headers,
            "client": (ip, 4567),
            "server": ("testserver", 80),
        }
    )


class DocumentShareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.owner = User(
            username="owner",
            display_name="创建人",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.collaborator = User(
            username="collaborator",
            display_name="协作者",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.outsider = User(
            username="outsider",
            display_name="外部用户",
            password_hash="not-used",
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add_all([self.owner, self.collaborator, self.outsider])
        self.db.flush()
        self.document = Document(
            owner_id=self.owner.id,
            created_by_id=self.owner.id,
            last_modified_by_id=self.owner.id,
            title="公开文章",
            current_html="<p>初始正文</p>",
            visibility_mode=VisibilityMode.RESTRICTED,
        )
        self.document.allowed_users = [self.owner, self.collaborator]
        self.db.add(self.document)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def make_share(self) -> tuple[DocumentShare, str]:
        share, token = create_share(self.db, self.document, self.owner, utcnow() + timedelta(days=7))
        self.db.commit()
        self.db.refresh(share)
        return share, token

    def test_token_is_hashed_at_rest_and_collaborator_can_manage(self) -> None:
        share, token = self.make_share()

        self.assertEqual(share.token_hash, token_hash(token))
        self.assertNotEqual(share.token_encrypted, token)
        entries = document_shares.list_document_shares(self.document.id, self.collaborator, self.db)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].token, token)

        with self.assertRaises(HTTPException) as context:
            document_shares.list_document_shares(self.document.id, self.outsider, self.db)
        self.assertEqual(context.exception.status_code, 404)

    def test_public_reader_tracks_one_visit_per_session_and_observes_revision(self) -> None:
        share, token = self.make_share()
        request = make_request()
        response = Response()

        payload = document_shares.get_public_document_share(token, request, response, self.db)
        self.assertEqual(payload.title, "公开文章")
        self.assertEqual(payload.html, "<p>初始正文</p>")
        self.assertEqual(payload.cover_url, "")
        self.assertEqual(payload.expires_at.tzinfo, timezone.utc)
        self.assertEqual(payload.revision, document_revision(self.document))
        self.assertIn("document_share_visit_", response.headers["set-cookie"])
        self.assertEqual(self.db.query(DocumentShareVisit).count(), 1)

        record_public_visit(self.db, share, request, "same-browser-session")
        record_public_visit(self.db, share, request, "same-browser-session")
        self.assertEqual(self.db.query(DocumentShareVisit).count(), 2)
        visit = self.db.query(DocumentShareVisit).filter(DocumentShareVisit.visitor_session_hash == token_hash("same-browser-session")).one()
        self.assertEqual(visit.ip_address, "203.0.113.7")
        self.assertEqual(visit.user_agent, "ShareTest/1.0")
        self.assertEqual(visit.referer, "https://example.test/")

        self.document.current_html = "<p>AI 已更新</p>"
        self.document.title = "更新后的文章"
        self.db.commit()
        revision = document_shares.get_public_document_share_revision(token, Response(), self.db)
        self.assertEqual(revision.expires_at.tzinfo, timezone.utc)
        self.assertEqual(revision.revision, document_revision(self.document))
        self.assertNotEqual(revision.revision, payload.revision)

    def test_public_reader_exposes_cover_and_refreshes_its_revision(self) -> None:
        share, token = self.make_share()
        self.document.wechat_cover_url = "https://covers.example.test/article.jpg"
        self.db.commit()

        payload = document_shares.get_public_document_share(token, make_request(), Response(), self.db)
        self.assertEqual(payload.cover_url, "https://covers.example.test/article.jpg")
        original_revision = payload.revision

        self.document.wechat_cover_url = "https://covers.example.test/article-next.jpg"
        self.db.commit()
        revision = document_shares.get_public_document_share_revision(token, Response(), self.db)
        self.assertNotEqual(revision.revision, original_revision)

    def test_expired_and_revoked_links_are_gone(self) -> None:
        share, token = self.make_share()
        revoke_share(share, self.owner)
        self.db.commit()

        with self.assertRaises(HTTPException) as context:
            document_shares.get_public_document_share(token, make_request(), Response(), self.db)
        self.assertEqual(context.exception.status_code, 410)

        expired, expired_token = create_share(self.db, self.document, self.owner, utcnow() + timedelta(seconds=1))
        expired.expires_at = utcnow() - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaises(HTTPException) as context:
            document_shares.get_public_document_share(expired_token, make_request(), Response(), self.db)
        self.assertEqual(context.exception.status_code, 410)

    def test_document_deletion_revokes_links_and_preserves_visit_rows(self) -> None:
        share, token = self.make_share()
        document_shares.get_public_document_share(token, make_request(), Response(), self.db)
        self.assertEqual(self.db.query(DocumentShareVisit).count(), 1)
        revoked = revoke_document_shares(self.db, self.document, self.owner)
        self.db.commit()
        self.db.refresh(share)
        self.assertEqual(revoked, 1)
        self.assertIsNone(share.document_id)
        self.assertIsNotNone(share.revoked_at)
        self.assertEqual(self.db.query(DocumentShareVisit).count(), 1)

    def test_forwarded_ip_is_used_only_for_a_trusted_proxy(self) -> None:
        trusted_settings = SimpleNamespace(trusted_proxy_cidrs_list=["127.0.0.0/8"])
        with patch("app.services.document_shares.get_settings", return_value=trusted_settings):
            self.assertEqual(
                request_ip_address(make_request(ip="127.0.0.1", forwarded_for="198.51.100.9, 127.0.0.1")),
                "198.51.100.9",
            )
            self.assertEqual(
                request_ip_address(make_request(ip="203.0.113.7", forwarded_for="198.51.100.9")),
                "203.0.113.7",
            )

if __name__ == "__main__":
    unittest.main()
