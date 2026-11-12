"""Audit SQL must let the event loop release a busy database connection."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import app.models  # noqa: F401
from app.core.security import create_access_token
from app.db.base import Base
from app.main import operation_audit
from app.models.operation_log import OperationLog
from app.models.user import User, UserRole
from app.services.operation_logs import capture_request_context


class OperationLogConnectionPoolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.directory.name) / 'pool.db'}",
            connect_args={"check_same_thread": False},
            pool_size=1, max_overflow=0, pool_timeout=0.3,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        with self.Session() as db:
            db.add(User(id=1, username="pool-admin", display_name="Pool test",
                        password_hash="unused", role=UserRole.ADMIN, is_active=True))
            db.commit()
        self.token = create_access_token("1")
        self.audit = patch("app.services.operation_logs.SessionLocal", self.Session)
        self.audit.start()

    def tearDown(self):
        self.audit.stop()
        self.assertEqual(self.engine.pool.checkedout(), 0)
        self.engine.dispose()
        self.directory.cleanup()

    def request(self):
        return Request({
            "type": "http", "method": "POST", "scheme": "http",
            "path": "/api/documents", "query_string": b"",
            "headers": [(b"authorization", f"Bearer {self.token}".encode())],
            "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
        })

    def test_actor_snapshot_allows_event_loop_to_release_busy_connection(self):
        async def scenario():
            holder = self.engine.connect()
            release = asyncio.get_running_loop().call_later(0.05, holder.close)
            try:
                context = await capture_request_context(self.request())
                self.assertEqual(context.actor_username, "pool-admin")
            finally:
                release.cancel()
                holder.close()
        asyncio.run(scenario())

    def test_successful_request_is_audited_after_pool_recovers(self):
        self.check_audit_write(fail=False)

    def test_failed_request_is_audited_after_pool_recovers(self):
        self.check_audit_write(fail=True)

    def check_audit_write(self, *, fail):
        async def scenario():
            holders, releases = [], []

            async def endpoint(_request):
                holder = self.engine.connect()
                holders.append(holder)
                releases.append(asyncio.get_running_loop().call_later(0.05, holder.close))
                if fail:
                    raise ValueError("test failure")
                return JSONResponse({"id": 1}, status_code=201)

            try:
                if fail:
                    with self.assertRaisesRegex(ValueError, "test failure"):
                        await operation_audit(self.request(), endpoint)
                else:
                    response = await operation_audit(self.request(), endpoint)
                    self.assertEqual(response.status_code, 201)
            finally:
                for release in releases:
                    release.cancel()
                for holder in holders:
                    holder.close()
        asyncio.run(scenario())
        with self.Session() as db:
            audit = db.query(OperationLog).filter_by(action="document.create").one()
            self.assertEqual(audit.actor_username, "pool-admin")
            self.assertEqual(audit.error_summary, "服务器处理失败" if fail else "")


if __name__ == "__main__":
    unittest.main()
