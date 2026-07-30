from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401 - register every table.
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.workboard import _period_range, get_workboard
from app.db.base import Base
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.document import Document
from app.models.document_version import DocumentVersion, DocumentVersionSource
from app.models.model_call_record import ModelCallRecord, ModelCallSource, ModelCallStatus
from app.models.user import User, UserRole


class WorkboardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        provider = AIProvider(name="test", provider_type=ProviderType.OPENAI_COMPATIBLE, base_url="https://example.test")
        self.admin = User(username="admin", display_name="管理员", password_hash="x", role=UserRole.ADMIN)
        self.alice = User(username="alice", display_name="爱丽丝", password_hash="x", role=UserRole.USER)
        self.bob = User(username="bob", display_name="鲍勃", password_hash="x", role=UserRole.USER)
        self.db.add_all([provider, self.admin, self.alice, self.bob])
        self.db.flush()
        self.public_model = AIModel(provider_id=provider.id, model_name="public", display_name="公共模型")
        self.restricted_model = AIModel(
            provider_id=provider.id,
            model_name="restricted",
            display_name="受限模型",
            access_mode="restricted",
        )
        self.restricted_model.allowed_users.append(self.bob)
        self.db.add_all([self.public_model, self.restricted_model])
        self.db.flush()
        now = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.db.add_all(
            [
                ModelCallRecord(
                    model_id=self.public_model.id,
                    user_id=self.alice.id,
                    source=ModelCallSource.AGENT,
                    source_id="run-public",
                    status=ModelCallStatus.COMPLETED,
                    usage_reported=True,
                    input_tokens=100,
                    output_tokens=30,
                    cache_read_tokens=60,
                    cache_write_tokens=10,
                    started_at=now,
                    finished_at=now,
                ),
                ModelCallRecord(
                    model_id=self.restricted_model.id,
                    user_id=self.bob.id,
                    source=ModelCallSource.AGENT,
                    source_id="run-restricted",
                    status=ModelCallStatus.COMPLETED,
                    usage_reported=True,
                    input_tokens=400,
                    output_tokens=80,
                    cache_read_tokens=300,
                    cache_write_tokens=20,
                    started_at=now,
                    finished_at=now,
                ),
                ModelCallRecord(
                    model_id=self.public_model.id,
                    user_id=self.alice.id,
                    source=ModelCallSource.AGENT_RUNTIME_COMPACTION,
                    source_id="run-unreported",
                    status=ModelCallStatus.COMPLETED,
                    usage_reported=False,
                    started_at=now,
                    finished_at=now,
                ),
            ]
        )
        document = Document(
            owner_id=self.alice.id,
            created_by_id=self.alice.id,
            last_modified_by_id=self.alice.id,
            title="统计推文",
            current_html="<p>正文</p>",
            created_at=now,
        )
        self.db.add(document)
        self.db.flush()
        self.db.add_all(
            [
                DocumentVersion(
                    document_id=document.id,
                    version_number=1,
                    title=document.title,
                    html=document.current_html,
                    source=DocumentVersionSource.AI,
                    created_by_id=self.alice.id,
                    created_at=now,
                ),
                DocumentVersion(
                    document_id=document.id,
                    version_number=2,
                    title=document.title,
                    html=document.current_html,
                    source=DocumentVersionSource.RESTORE,
                    created_by_id=self.alice.id,
                    created_at=now,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_model_statistics_are_strictly_scoped_to_accessible_models(self) -> None:
        payload = get_workboard("30d", self.alice, self.db)

        self.assertEqual(payload.overview.model_call_count, 2)
        self.assertEqual(payload.overview.input_tokens, 100)
        self.assertEqual(payload.overview.cache_read_tokens, 60)
        self.assertEqual(payload.overview.cache_hit_rate, 60)
        self.assertEqual(payload.overview.usage_unreported_calls, 1)
        self.assertEqual([row.display_name for row in payload.model_ranking], ["公共模型"])
        self.assertEqual([row.display_name for row in payload.user_ranking], ["爱丽丝"])

    def test_admin_sees_all_models_and_tweet_creation_activity(self) -> None:
        payload = get_workboard("30d", self.admin, self.db)

        self.assertEqual(payload.overview.model_call_count, 3)
        self.assertEqual(payload.overview.input_tokens, 500)
        self.assertEqual({row.display_name for row in payload.model_ranking}, {"公共模型", "受限模型"})
        self.assertEqual(payload.tweet_activity.total_documents, 1)
        self.assertEqual(payload.tweet_activity.created_documents, 1)
        self.assertEqual(payload.tweet_activity.active_creators, 1)
        self.assertEqual(payload.tweet_activity.ai_versions, 1)
        self.assertEqual(payload.tweet_activity.manual_versions, 1)

    def test_today_uses_shanghai_midnight(self) -> None:
        start, end = _period_range("today", datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc))

        self.assertEqual(start, datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc))
