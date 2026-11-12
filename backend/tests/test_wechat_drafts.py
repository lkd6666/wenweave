import asyncio
import base64
import hashlib
import ipaddress
import json
import shutil
import unittest
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.routes import documents, wechat_accounts
from app.core.crypto import encrypt_secret
from app.db.base import Base
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.document_visibility import VisibilityMode
from app.models.template_library import TemplateImageAsset, TemplateLibraryItem, TemplateSourceType
from app.models.user import User, UserRole
from app.models.user_group import UserGroup
from app.models.wechat_account import (
    WeChatAccount,
    WeChatBodyImageMaterial,
    WeChatCoverMaterial,
    WeChatDraft,
    WeChatDraftStatus,
    WeChatDraftSyncMode,
)
from app.schemas.document import DocumentDetail, DocumentUpdate
from app.schemas.wechat import WeChatAccountCreate, WeChatAccountUpdate, WeChatArticleMetadata, WeChatDraftCreate
from app.services.wechat_official_account import (
    BodyImageCacheEntry,
    CoverImage,
    DraftPushResult,
    DraftTarget,
    ImagePayload,
    WeChatApiError,
    WECHAT_EMPTY_DIGEST_PLACEHOLDER,
    WeChatOfficialAccountClient,
    _redact_sensitive_text,
)
from app.services.image_localization import ImageLocalizationResult
from app.services import local_uploads


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
TEST_TMP_PARENT = Path(__file__).resolve().parents[1] / "data" / "test-temp"


class WeChatAccountAndDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_PARENT.mkdir(parents=True, exist_ok=True)
        self.directory = TEST_TMP_PARENT / f"tmp-{uuid4().hex}"
        self.directory.mkdir(parents=True)
        self.local_root = patch.object(local_uploads, "LOCAL_UPLOAD_ROOT", self.directory)
        self.local_root.start()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.admin = User(username="admin", display_name="管理员", password_hash="x", role=UserRole.ADMIN, is_active=True)
        self.user = User(username="writer", display_name="作者", password_hash="x", role=UserRole.USER, is_active=True)
        self.other_user = User(username="other", display_name="其他", password_hash="x", role=UserRole.USER, is_active=True)
        self.db.add_all([self.admin, self.user, self.other_user])
        self.db.commit()
        self.document = Document(
            owner_id=self.user.id,
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
            title="文章标题",
            current_html="<p>正文</p>",
        )
        self.db.add(self.document)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.local_root.stop()
        shutil.rmtree(self.directory, ignore_errors=True)

    def make_account(self, users: list[User] | None = None, active: bool = True) -> WeChatAccount:
        account = WeChatAccount(
            name="测试号",
            app_id=f"wx-{self.db.query(WeChatAccount).count()}",
            app_secret_encrypted=encrypt_secret("test-secret"),
            is_active=active,
        )
        account.allowed_users = users or []
        self.db.add(account)
        self.db.commit()
        return account

    def add_template_asset(self, asset_id: str) -> None:
        template = TemplateLibraryItem(name="组件", html="<p>组件</p>", source_type=TemplateSourceType.SOURCE)
        self.db.add(template)
        self.db.flush()
        object_key = f"local/template-library/{asset_id}.png"
        local_uploads.save_bytes(object_key, PNG, lambda _path: None)
        self.db.add(TemplateImageAsset(
            id=asset_id,
            template_id=template.id,
            original_url="https://source.example.test/component.png",
            object_key=object_key,
            storage_mode="local",
            content_type="image/png",
            size=len(PNG),
        ))
        self.db.commit()

    def local_cover_url(self) -> str:
        image_name = f"{'c' * 32}.png"
        local_uploads.save_bytes(f"local/images/{image_name}", PNG, lambda _path: None)
        return f"/api/documents/local-images/{image_name}"

    def test_account_masks_secret_and_limits_available_accounts(self) -> None:
        account = self.make_account([self.user])
        created = wechat_accounts.create_account(
            WeChatAccountCreate(
                name="第二个号",
                app_id="wx-second",
                app_secret="another-secret",
                allowed_user_ids=[self.other_user.id],
            ),
            self.db,
        )
        self.assertNotIn("another-secret", created.app_secret_masked)
        self.assertEqual(
            [item.id for item in wechat_accounts.list_available_accounts(self.user, self.db)],
            [account.id],
        )
        self.assertEqual(
            [item.id for item in wechat_accounts.list_available_accounts(self.admin, self.db)],
            [account.id, created.id],
        )

    def test_authorized_user_group_can_push_and_revocation_takes_effect(self) -> None:
        group = UserGroup(name="新媒体中心")
        group.members.append(self.user)
        self.db.add(group)
        self.db.commit()

        created = wechat_accounts.create_account(
            WeChatAccountCreate(
                name="用户组授权号",
                app_id="wx-group-access",
                app_secret="group-secret",
                allowed_group_ids=[group.id],
            ),
            self.db,
        )
        account = self.db.get(WeChatAccount, created.id)
        assert account is not None

        self.assertEqual(created.allowed_group_ids, [group.id])
        self.assertEqual(
            [item.id for item in wechat_accounts.list_available_accounts(self.user, self.db)],
            [account.id],
        )
        self.assertEqual(wechat_accounts.list_available_accounts(self.other_user, self.db), [])
        self.assertTrue(documents._can_push_wechat_draft(self.user, account))
        self.assertFalse(documents._can_push_wechat_draft(self.other_user, account))

        updated = wechat_accounts.update_account(
            account.id,
            WeChatAccountUpdate(allowed_group_ids=[]),
            self.db,
        )
        self.assertEqual(updated.allowed_group_ids, [])
        self.assertEqual(wechat_accounts.list_available_accounts(self.user, self.db), [])
        self.db.refresh(account)
        self.assertFalse(documents._can_push_wechat_draft(self.user, account))

    def test_metadata_is_saved_without_creating_a_document_version(self) -> None:
        metadata = WeChatArticleMetadata(
            title="草稿标题",
            author="作者",
            digest="摘要",
            content_source_url="https://example.com/read",
            cover_url="https://cdn.example.com/cover.png",
            pic_crop_235_1="0_0_1_1",
            pic_crop_1_1="0_0_1_1",
            need_open_comment=True,
            only_fans_can_comment=True,
        )
        documents.update_document(self.document.id, DocumentUpdate(wechat_metadata=metadata), self.user, self.db)
        self.db.refresh(self.document)
        self.assertEqual(self.document.title, "草稿标题")
        self.assertEqual(self.document.wechat_title, "草稿标题")
        self.assertEqual(self.document.wechat_metadata["title"], "草稿标题")
        self.assertEqual(self.document.wechat_metadata["cover_url"], "https://cdn.example.com/cover.png")
        self.assertTrue(self.document.wechat_need_open_comment)

    def test_system_title_update_also_updates_wechat_title(self) -> None:
        documents.update_document(self.document.id, DocumentUpdate(title="同步后的标题"), self.user, self.db)
        self.db.refresh(self.document)

        self.assertEqual(self.document.title, "同步后的标题")
        self.assertEqual(self.document.wechat_title, "同步后的标题")
        self.assertEqual(self.document.wechat_metadata["title"], "同步后的标题")

    def test_rejects_request_with_conflicting_system_and_wechat_titles(self) -> None:
        with self.assertRaises(Exception) as context:
            documents.update_document(
                self.document.id,
                DocumentUpdate(
                    title="系统标题",
                    wechat_metadata=WeChatArticleMetadata(title="不同的微信标题"),
                ),
                self.user,
                self.db,
            )

        self.assertEqual(getattr(context.exception, "status_code", None), 422)
        self.db.refresh(self.document)
        self.assertEqual(self.document.title, "文章标题")
        self.assertEqual(self.document.wechat_title, "文章标题")

    def test_long_document_title_allows_metadata_updates_but_blocks_wechat_sync(self) -> None:
        for length in (65, 256):
            with self.subTest(length=length):
                title = "长" * length
                document = documents.update_document(
                    self.document.id, DocumentUpdate(title=title), self.user, self.db,
                )
                detail = DocumentDetail.model_validate(document)
                self.assertEqual(detail.wechat_metadata.title, title)
                metadata = detail.wechat_metadata.model_copy(update={"author": "作者"})
                updated = documents.update_document(
                    self.document.id,
                    DocumentUpdate.model_validate({"wechat_metadata": metadata.model_dump()}),
                    self.user,
                    self.db,
                )
                self.assertEqual(DocumentDetail.model_validate(updated).wechat_metadata.title, title)
                self.assertEqual(updated.wechat_author, "作者")

                account = self.make_account([self.user])
                with (
                    patch("app.api.routes.documents.WeChatOfficialAccountClient") as client,
                    self.assertRaises(HTTPException) as raised,
                ):
                    asyncio.run(documents.create_wechat_draft(
                        self.document.id, WeChatDraftCreate(account_id=account.id), self.user, self.db,
                    ))
                self.assertEqual(raised.exception.status_code, 422)
                self.assertIn("64", raised.exception.detail)
                client.assert_not_called()

    def test_active_agent_run_blocks_wechat_draft_push(self) -> None:
        self.db.add(
            AgentRun(
                id="active-wechat-draft-run",
                document_id=self.document.id,
                session_id=1,
                user_id=self.user.id,
                user_message_id=1,
                client_request_id="active-wechat-draft-request",
                status=AgentRunStatus.RUNNING,
            )
        )
        self.db.commit()

        self.assertTrue(documents.list_documents(self.user, self.db)[0].is_ai_editing)
        with self.assertRaises(Exception) as context:
            asyncio.run(
                documents.create_wechat_draft(
                    self.document.id,
                    WeChatDraftCreate(account_id=999),
                    self.user,
                    self.db,
                )
            )

        self.assertEqual(getattr(context.exception, "status_code", None), 409)
        self.assertIn("正在由 AI 编辑", str(context.exception.detail))

    def test_wechat_draft_history_is_shared_by_all_document_users(self) -> None:
        account = self.make_account([self.user])
        self.db.add_all([
            WeChatDraft(
                document_id=self.document.id,
                account_id=account.id,
                created_by_id=self.user.id,
                status=WeChatDraftStatus.SUCCEEDED,
                sync_mode=WeChatDraftSyncMode.CREATE,
                media_id="writer-media",
                article_title="作者同步的草稿",
            ),
            WeChatDraft(
                document_id=self.document.id,
                account_id=account.id,
                created_by_id=self.admin.id,
                status=WeChatDraftStatus.FAILED,
                sync_mode=WeChatDraftSyncMode.UPDATE,
                article_title="管理员同步的草稿",
                error_message="测试失败信息",
            ),
        ])
        self.db.commit()

        history = documents.list_wechat_drafts(self.document.id, self.other_user, self.db)

        self.assertEqual([item.article_title for item in history], ["管理员同步的草稿", "作者同步的草稿"])
        self.assertEqual([item.created_by_name for item in history], ["管理员", "作者"])

    def test_ai_editing_status_only_includes_accessible_active_documents(self) -> None:
        self.document.visibility_mode = VisibilityMode.RESTRICTED
        self.document.allowed_users = [self.user]
        self.db.add(
            AgentRun(
                id="active-status-run",
                document_id=self.document.id,
                session_id=1,
                user_id=self.user.id,
                user_message_id=1,
                client_request_id="active-status-request",
                status=AgentRunStatus.RUNNING,
            )
        )
        self.db.commit()

        self.assertEqual(documents.get_ai_editing_status(self.user, self.db).active_document_ids, [self.document.id])
        self.assertEqual(documents.get_ai_editing_status(self.other_user, self.db).active_document_ids, [])

    def test_draft_route_enforces_account_access_and_caches_cover_media(self) -> None:
        account = self.make_account([self.user])
        self.document.wechat_title = "草稿标题"
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.db.commit()
        cover = CoverImage(b"cover", "image/png", "cover.png")
        client = type("MockClient", (), {
            "download_cover": AsyncMock(return_value=cover),
            "create_draft": AsyncMock(return_value=DraftPushResult(
                "draft-media",
                "cover-media",
                True,
                (BodyImageCacheEntry("a" * 64, "b" * 64, "image/png", "https://mmbiz.qpic.cn/body.png", "temporary"),),
            )),
        })()
        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            result = asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id), self.user, self.db
                )
            )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.media_id, "draft-media")
        self.assertEqual(self.db.query(WeChatDraft).one().status, WeChatDraftStatus.SUCCEEDED)
        self.assertEqual(self.db.query(WeChatCoverMaterial).one().media_id, "cover-media")
        self.assertEqual(self.db.query(WeChatBodyImageMaterial).one().wechat_url, "https://mmbiz.qpic.cn/body.png")

    def test_push_automatically_localizes_article_images_before_submitting_draft(self) -> None:
        account = self.make_account([self.user])
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.document.current_html = '<p><img src="data:image/png;base64,AAAA"></p>'
        self.db.commit()
        localized_html = '<p><img src="/api/documents/local-images/localized.png"></p>'
        client = type("MockClient", (), {
            "download_cover": AsyncMock(return_value=CoverImage(b"cover", "image/png", "cover.png")),
            "create_draft": AsyncMock(return_value=DraftPushResult("draft-media", "cover-media", True)),
        })()

        with patch(
            "app.api.routes.documents.localize_document_html",
            new=AsyncMock(return_value=ImageLocalizationResult(localized_html, 1, {})),
        ) as localize, patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id), self.user, self.db
                )
            )

        localize.assert_awaited_once_with(self.db, self.document, '<p><img src="data:image/png;base64,AAAA"></p>')
        self.db.refresh(self.document)
        self.assertEqual(self.document.current_html, localized_html)
        self.assertEqual(client.create_draft.await_args.kwargs["html"], localized_html)
        self.assertEqual(self.db.query(DocumentVersion).one().label, "同步前自动转存图片")

        blocked = self.make_account([self.other_user])
        with self.assertRaises(Exception) as context:
            asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=blocked.id), self.user, self.db
                )
            )
        self.assertEqual(getattr(context.exception, "status_code", None), 403)

    def test_push_repairs_historical_template_asset_urls_before_wechat_client(self) -> None:
        account = self.make_account([self.user])
        asset_id = "33333333-3333-3333-3333-333333333333"
        self.add_template_asset(asset_id)
        self.document.wechat_cover_url = self.local_cover_url()
        self.document.current_html = (
            f'<section style="background-image:url(\'/api/template-library/assets/{asset_id}\');'
            f'background:#fff url(/api/template-library/assets/{asset_id}) no-repeat">'
            f'<img src="/api/template-library/assets/{asset_id}" '
            f'srcset="/api/template-library/assets/{asset_id} 1x, /api/template-library/assets/{asset_id} 2x"></section>'
        )
        self.db.commit()
        client = type("MockClient", (), {
            "download_cover": AsyncMock(),
            "create_draft": AsyncMock(return_value=DraftPushResult("draft-media", "cover-media", True)),
        })()

        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id), self.user, self.db
                )
            )

        submitted_html = client.create_draft.await_args.kwargs["html"]
        self.assertNotIn("/api/template-library/assets/", submitted_html)
        self.assertNotIn("https://app.example.test/api/template-library/assets/", submitted_html)
        self.assertIn("/api/documents/local-images/", submitted_html)
        self.db.refresh(self.document)
        self.assertEqual(self.document.current_html, submitted_html)
        self.assertEqual(self.db.query(DocumentVersion).one().label, "同步前自动转存图片")
        client.download_cover.assert_not_awaited()

    def test_unexpected_push_failure_is_recorded_with_a_safe_error(self) -> None:
        account = self.make_account([self.user])
        self.document.wechat_title = "草稿标题"
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.db.commit()
        client = type("MockClient", (), {
            "download_cover": AsyncMock(return_value=CoverImage(b"cover", "image/png", "cover.png")),
            "create_draft": AsyncMock(side_effect=RuntimeError("production-only diagnostic")),
        })()

        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            with self.assertRaises(Exception) as context:
                asyncio.run(
                    documents.create_wechat_draft(
                        self.document.id, WeChatDraftCreate(account_id=account.id), self.user, self.db
                    )
                )

        self.assertEqual(getattr(context.exception, "status_code", None), 500)
        self.assertIn("已记录失败", str(context.exception.detail))
        self.assertNotIn("production-only diagnostic", str(context.exception.detail))
        failed_draft = self.db.query(WeChatDraft).one()
        self.assertEqual(failed_draft.status, WeChatDraftStatus.FAILED)
        self.assertIn("已记录失败", failed_draft.error_message)

    def test_stream_hides_internal_error_but_includes_a_request_reference(self) -> None:
        async def consume(response) -> str:
            return "".join([chunk async for chunk in response.body_iterator])

        with patch(
            "app.api.routes.documents._push_wechat_draft",
            new=AsyncMock(side_effect=RuntimeError("production-only diagnostic")),
        ), patch("app.api.routes.documents.SessionLocal", self.Session), patch(
            "app.api.routes.documents.get_operation_request_id", return_value="wechat-request-123"
        ):
            response = asyncio.run(
                documents.stream_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=1), self.user, self.db
                )
            )
            payload = asyncio.run(consume(response))

        self.assertIn('"status": 500', payload)
        self.assertIn("请求编号 wechat-request-123", payload)
        self.assertNotIn("production-only diagnostic", payload)

    def test_stream_reloads_a_detached_user_before_checking_group_access(self) -> None:
        group = UserGroup(name="流式推送组")
        group.members.append(self.user)
        self.db.add(group)
        self.db.commit()
        account = self.make_account()
        account.allowed_groups = [group]
        self.document.wechat_cover_url = self.local_cover_url()
        self.db.commit()

        self.assertIsInstance(self.user.id, int)
        self.db.expire(self.user, ["groups"])
        self.db.expunge(self.user)
        self.assertTrue(inspect(self.user).detached)
        client = type("MockClient", (), {
            "create_draft": AsyncMock(return_value=DraftPushResult("draft-media", "cover-media", True)),
        })()

        async def consume(response) -> str:
            return "".join([chunk async for chunk in response.body_iterator])

        with patch("app.api.routes.documents.SessionLocal", self.Session), patch(
            "app.api.routes.documents.WeChatOfficialAccountClient", return_value=client
        ):
            response = asyncio.run(
                documents.stream_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id), self.user, self.db
                )
            )
            response_payload = asyncio.run(consume(response))

        self.assertIn('event: result', response_payload)
        self.assertNotIn('event: error', response_payload)
        self.assertEqual(self.db.query(WeChatDraft).one().status, WeChatDraftStatus.SUCCEEDED)

    def test_draft_route_updates_selected_remote_draft_and_records_mode(self) -> None:
        account = self.make_account([self.user])
        self.document.wechat_title = "草稿标题"
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.db.commit()
        cover = CoverImage(b"cover", "image/png", "cover.png")
        client = type("MockClient", (), {
            "validate_draft_target": AsyncMock(return_value=DraftTarget("target-media", "原草稿", None, 1)),
            "download_cover": AsyncMock(return_value=cover),
            "update_draft": AsyncMock(return_value=DraftPushResult("target-media", "cover-media", True)),
            "create_draft": AsyncMock(),
        })()
        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            result = asyncio.run(
                documents.create_wechat_draft(
                    self.document.id,
                    WeChatDraftCreate(
                        account_id=account.id,
                        sync_mode="update",
                        target_media_id="target-media",
                    ),
                    self.user,
                    self.db,
                )
            )

        self.assertEqual(result.media_id, "target-media")
        self.assertEqual(result.sync_mode, "update")
        client.validate_draft_target.assert_awaited_once_with(account, "target-media")
        client.update_draft.assert_awaited_once()
        client.create_draft.assert_not_awaited()
        self.assertEqual(self.db.query(WeChatDraft).one().sync_mode, WeChatDraftSyncMode.UPDATE)

    def test_auto_sync_updates_latest_successful_draft_for_the_same_account(self) -> None:
        account = self.make_account([self.user])
        self.document.wechat_title = "草稿标题"
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.db.add(
            WeChatDraft(
                document_id=self.document.id,
                account_id=account.id,
                created_by_id=self.user.id,
                status=WeChatDraftStatus.SUCCEEDED,
                sync_mode=WeChatDraftSyncMode.CREATE,
                media_id="previous-media",
                article_title="旧草稿",
            )
        )
        self.db.commit()
        client = type("MockClient", (), {
            "download_cover": AsyncMock(return_value=CoverImage(b"cover", "image/png", "cover.png")),
            "validate_draft_target": AsyncMock(return_value=DraftTarget("previous-media", "旧草稿", None, 1)),
            "update_draft": AsyncMock(return_value=DraftPushResult("previous-media", "cover-media", True)),
            "create_draft": AsyncMock(),
        })()
        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            result = asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id, sync_mode="auto"), self.user, self.db
                )
            )

        self.assertEqual(result.sync_mode, "update")
        client.validate_draft_target.assert_awaited_once_with(account, "previous-media")
        client.update_draft.assert_awaited_once()
        self.assertEqual(client.update_draft.await_args.kwargs["target_media_id"], "previous-media")
        client.create_draft.assert_not_awaited()

    def test_auto_sync_creates_a_new_draft_when_only_another_account_has_history(self) -> None:
        previous_account = self.make_account([self.user])
        account = self.make_account([self.user])
        self.document.wechat_title = "草稿标题"
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.db.add(
            WeChatDraft(
                document_id=self.document.id,
                account_id=previous_account.id,
                created_by_id=self.user.id,
                status=WeChatDraftStatus.SUCCEEDED,
                sync_mode=WeChatDraftSyncMode.CREATE,
                media_id="previous-account-media",
                article_title="另一个公众号的草稿",
            )
        )
        self.db.commit()
        client = type("MockClient", (), {
            "download_cover": AsyncMock(return_value=CoverImage(b"cover", "image/png", "cover.png")),
            "create_draft": AsyncMock(return_value=DraftPushResult("new-media", "cover-media", True)),
            "update_draft": AsyncMock(),
        })()
        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            result = asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id, sync_mode="auto"), self.user, self.db
                )
            )

        self.assertEqual(result.sync_mode, "create")
        client.create_draft.assert_awaited_once()
        client.update_draft.assert_not_awaited()

    def test_auto_sync_creates_a_new_draft_when_the_previous_draft_has_been_deleted(self) -> None:
        account = self.make_account([self.user])
        self.document.wechat_title = "草稿标题"
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.db.add(
            WeChatDraft(
                document_id=self.document.id,
                account_id=account.id,
                created_by_id=self.user.id,
                status=WeChatDraftStatus.SUCCEEDED,
                sync_mode=WeChatDraftSyncMode.CREATE,
                media_id="deleted-media",
                article_title="已删除草稿",
            )
        )
        self.db.commit()
        client = type("MockClient", (), {
            "download_cover": AsyncMock(return_value=CoverImage(b"cover", "image/png", "cover.png")),
            "validate_draft_target": AsyncMock(side_effect=WeChatApiError("invalid media_id", 40007)),
            "update_draft": AsyncMock(),
            "create_draft": AsyncMock(return_value=DraftPushResult("new-media", "cover-media", True)),
        })()
        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            result = asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id, sync_mode="auto"), self.user, self.db
                )
            )

        self.assertEqual(result.sync_mode, "create")
        self.assertEqual(result.media_id, "new-media")
        client.validate_draft_target.assert_awaited_once_with(account, "deleted-media")
        client.update_draft.assert_not_awaited()
        client.create_draft.assert_awaited_once()
        created_draft = self.db.query(WeChatDraft).order_by(WeChatDraft.id.desc()).first()
        self.assertEqual(created_draft.status, WeChatDraftStatus.SUCCEEDED)
        self.assertEqual(created_draft.sync_mode, WeChatDraftSyncMode.CREATE)
        self.assertEqual(created_draft.media_id, "new-media")

    def test_auto_sync_creates_a_new_draft_when_the_target_disappears_after_validation(self) -> None:
        account = self.make_account([self.user])
        self.document.wechat_title = "草稿标题"
        self.document.wechat_cover_url = "https://cdn.example.com/cover.png"
        self.db.add(
            WeChatDraft(
                document_id=self.document.id,
                account_id=account.id,
                created_by_id=self.user.id,
                status=WeChatDraftStatus.SUCCEEDED,
                sync_mode=WeChatDraftSyncMode.CREATE,
                media_id="deleted-during-sync-media",
                article_title="即将删除草稿",
            )
        )
        self.db.commit()
        client = type("MockClient", (), {
            "download_cover": AsyncMock(return_value=CoverImage(b"cover", "image/png", "cover.png")),
            "validate_draft_target": AsyncMock(return_value=DraftTarget("deleted-during-sync-media", "即将删除草稿", None, 1)),
            "update_draft": AsyncMock(return_value=DraftPushResult("new-media", "cover-media", True, created_new_draft=True)),
            "create_draft": AsyncMock(),
        })()

        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            result = asyncio.run(
                documents.create_wechat_draft(
                    self.document.id, WeChatDraftCreate(account_id=account.id, sync_mode="auto"), self.user, self.db
                )
            )

        self.assertEqual(result.sync_mode, "create")
        client.update_draft.assert_awaited_once()
        self.assertTrue(client.update_draft.await_args.kwargs["fallback_to_create_on_invalid_target"])
        client.create_draft.assert_not_awaited()

    def test_draft_target_route_lists_remote_drafts_for_permitted_account(self) -> None:
        account = self.make_account([self.user])
        client = type("MockClient", (), {
            "list_draft_targets": AsyncMock(return_value=[DraftTarget("media-1", "要覆盖的草稿", 1_700_000_000, 2)]),
        })()
        with patch("app.api.routes.documents.WeChatOfficialAccountClient", return_value=client):
            targets = asyncio.run(
                documents.list_wechat_draft_targets(self.document.id, account.id, self.user, self.db)
            )

        self.assertEqual([(target.media_id, target.title, target.article_count) for target in targets], [("media-1", "要覆盖的草稿", 2)])
        client.list_draft_targets.assert_awaited_once_with(account)


class WeChatHttpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = WeChatAccount(
            id=101,
            name="测试号",
            app_id="wx-test",
            app_secret_encrypted=encrypt_secret("test-secret"),
        )

    def test_allows_large_body_for_wechat_to_validate(self) -> None:
        WeChatOfficialAccountClient.validate_draft_input(
            WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
            f"<p>{'正文' * 10_001}</p>",
        )

    def test_accepts_wechat_title_up_to_64_characters(self) -> None:
        title = "标题" * 32
        WeChatOfficialAccountClient.validate_draft_input(
            WeChatArticleMetadata(title=title, cover_url="https://images.example.com/cover.png"),
            "<p>正文</p>",
        )

    def test_rejects_long_title_before_sending_to_wechat(self) -> None:
        with self.assertRaisesRegex(WeChatApiError, "64"):
            WeChatOfficialAccountClient.validate_draft_input(
                WeChatArticleMetadata(title="长" * 65, cover_url="https://images.example.com/cover.png"),
                "<p>正文</p>",
            )

    def test_allows_browser_recoverable_p_section_nesting(self) -> None:
        WeChatOfficialAccountClient.validate_draft_input(
            WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
            '<section><p><section><img src="https://images.example.com/body.png"></section></p></section>',
        )

    def test_replaces_small_body_images_with_article_image_urls_and_retries_once_for_invalid_token(self) -> None:
        seen_paths: list[str] = []
        progress_events: list[tuple[str, int, str]] = []
        draft_attempts = 0

        async def report(stage: str, percent: int, detail: str) -> None:
            progress_events.append((stage, percent, detail))

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal draft_attempts
            seen_paths.append(request.url.path)
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": f"token-{seen_paths.count('/cgi-bin/stable_token')}", "expires_in": 7200})
            if request.url.host == "images.example.com":
                return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")
            if request.url.path == "/cgi-bin/media/uploadimg":
                call_number = seen_paths.count("/cgi-bin/media/uploadimg")
                return httpx.Response(200, json={"url": f"https://mmbiz.qpic.cn/temporary-{call_number}.png"})
            if request.url.path == "/cgi-bin/material/add_material":
                call_number = seen_paths.count("/cgi-bin/material/add_material")
                return httpx.Response(
                    200,
                    json={
                        "media_id": f"material-{call_number}",
                        "url": f"https://mmbiz.qpic.cn/permanent-{call_number}.png",
                    },
                )
            if request.url.path == "/cgi-bin/draft/add":
                draft_attempts += 1
                if draft_attempts == 1:
                    return httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid credential"})
                body = json.loads(request.content)
                self.assertIn("mmbiz.qpic.cn/temporary-2.png", body["articles"][0]["content"])
                self.assertEqual(body["articles"][0]["digest"], WECHAT_EMPTY_DIGEST_PLACEHOLDER)
                return httpx.Response(200, json={"media_id": "draft-media"})
            raise AssertionError(f"unexpected request {request.url}")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ), patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            result = asyncio.run(
                WeChatOfficialAccountClient().create_draft(
                    self.account,
                    html='<p><img src="https://images.example.com/a.png"></p>',
                    metadata=WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id=None,
                    progress_callback=report,
                )
            )
        self.assertEqual(result.media_id, "draft-media")
        self.assertEqual(seen_paths.count("/cgi-bin/stable_token"), 2)
        self.assertEqual(seen_paths.count("/cgi-bin/media/uploadimg"), 2)
        self.assertEqual(seen_paths.count("/cgi-bin/material/add_material"), 2)
        self.assertTrue(any(stage == "token" and "access_token" in detail for stage, _, detail in progress_events))
        self.assertTrue(any(stage == "body-images" and "正文图片 1/1" in detail for stage, _, detail in progress_events))
        self.assertTrue(any(stage == "cover" and "封面永久素材" in detail for stage, _, detail in progress_events))
        self.assertTrue(any(stage == "draft" and "草稿" in detail for stage, _, detail in progress_events))

    def test_preserves_gif_body_by_using_a_permanent_material_url(self) -> None:
        seen_paths: list[str] = []
        gif_bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            if request.url.host == "images.example.com":
                return httpx.Response(200, headers={"content-type": "image/gif"}, content=gif_bytes)
            if request.url.path == "/cgi-bin/material/add_material":
                if b"body.gif" in request.content:
                    self.assertIn(gif_bytes, request.content)
                    return httpx.Response(
                        200,
                        json={"media_id": "body-gif-media", "url": "https://mmbiz.qpic.cn/body.gif"},
                    )
                return httpx.Response(200, json={"media_id": "cover-media", "url": "https://mmbiz.qpic.cn/cover.gif"})
            if request.url.path == "/cgi-bin/draft/add":
                body = json.loads(request.content)
                self.assertIn("https://mmbiz.qpic.cn/body.gif", body["articles"][0]["content"])
                return httpx.Response(200, json={"media_id": "draft-media"})
            raise AssertionError(f"unexpected request {request.url}")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ), patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            result = asyncio.run(
                WeChatOfficialAccountClient().create_draft(
                    self.account,
                    html='<p><img src="https://images.example.com/body.gif"></p>',
                    metadata=WeChatArticleMetadata(title="动图", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id=None,
                )
        )

        self.assertEqual(result.media_id, "draft-media")
        self.assertEqual(seen_paths.count("/cgi-bin/media/uploadimg"), 0)
        self.assertEqual(seen_paths.count("/cgi-bin/material/add_material"), 2)

    def test_converts_webp_body_image_to_jpeg_before_upload(self) -> None:
        source_buffer = BytesIO()
        source_image = Image.new("RGB", (8, 6), (120, 30, 10))
        try:
            source_image.save(source_buffer, format="WEBP", lossless=True)
        finally:
            source_image.close()
        webp_bytes = source_buffer.getvalue()
        uploaded: list[tuple[str, str, bytes]] = []
        progress_events: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/webp"}, content=webp_bytes)

        async def upload_article_image(
            _client: httpx.AsyncClient, _token: str, *, payload: ImagePayload
        ) -> str:
            uploaded.append((payload.content_type, payload.filename, payload.read_bytes()))
            return "https://mmbiz.qpic.cn/converted.jpg"

        async def report(_stage: str, _percent: int, detail: str) -> None:
            progress_events.append(detail)

        client = WeChatOfficialAccountClient()
        client._upload_article_image = upload_article_image  # type: ignore[method-assign]
        transport = httpx.MockTransport(handler)

        async def replace():
            async with httpx.AsyncClient(transport=transport) as http_client:
                with patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
                    return await client._replace_body_images(
                        http_client,
                        "token",
                        '<p><img src="https://images.example.com/body.webp"></p>',
                        progress_callback=report,
                    )

        result = asyncio.run(replace())

        self.assertIn("https://mmbiz.qpic.cn/converted.jpg", result.html)
        self.assertEqual([(content_type, filename) for content_type, filename, _ in uploaded], [("image/jpeg", "body.jpg")])
        self.assertTrue(uploaded[0][2].startswith(b"\xff\xd8\xff"))
        self.assertEqual(result.cache_entries[0].content_type, "image/jpeg")
        self.assertTrue(any("正在将 WebP 转换" in detail for detail in progress_events))

    def test_reuploads_legacy_cached_body_image_url(self) -> None:
        source = "https://images.example.com/cached.png"
        source_hash = WeChatOfficialAccountClient.body_image_source_sha256(source)
        cached_entry = BodyImageCacheEntry(
            source_url_sha256=source_hash,
            content_sha256="a" * 64,
            content_type="image/png",
            wechat_url="https://mmbiz.qpic.cn/cached.png",
            upload_mode="temporary",
        )
        seen_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            if request.url.host == "images.example.com":
                return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")
            if request.url.path == "/cgi-bin/media/uploadimg":
                return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/reuploaded.png"})
            if request.url.path == "/cgi-bin/draft/add":
                body = json.loads(request.content)
                self.assertIn("https://mmbiz.qpic.cn/reuploaded.png", body["articles"][0]["content"])
                return httpx.Response(200, json={"media_id": "draft-media"})
            raise AssertionError(f"unexpected request {request.url}")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ), patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            result = asyncio.run(
                WeChatOfficialAccountClient().create_draft(
                    self.account,
                    html=f'<p><img src="{source}"></p>',
                    metadata=WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id="cover-media",
                    cached_body_images={source_hash: cached_entry},
                )
        )

        self.assertEqual(result.media_id, "draft-media")
        self.assertIn("/cgi-bin/media/uploadimg", seen_paths)
        self.assertEqual(result.body_image_cache_entries[0].upload_mode, "uploadimg")

    def test_reuses_matching_content_hash_for_a_new_body_image_url(self) -> None:
        previous_source = "https://images.example.com/old.png"
        source = "https://images.example.com/new.png"
        content = b"same-image"
        cached_entry = BodyImageCacheEntry(
            source_url_sha256=WeChatOfficialAccountClient.body_image_source_sha256(previous_source),
            content_sha256=hashlib.sha256(content).hexdigest(),
            content_type="image/png",
            wechat_url="https://mmbiz.qpic.cn/reused.png",
            upload_mode="uploadimg",
        )
        seen_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            if request.url.host == "images.example.com":
                return httpx.Response(200, headers={"content-type": "image/png"}, content=content)
            if request.url.path == "/cgi-bin/draft/add":
                body = json.loads(request.content)
                self.assertIn(cached_entry.wechat_url, body["articles"][0]["content"])
                return httpx.Response(200, json={"media_id": "draft-media"})
            raise AssertionError(f"unexpected request {request.url}")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ), patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            result = asyncio.run(
                WeChatOfficialAccountClient().create_draft(
                    self.account,
                    html=f'<p><img src="{source}"></p>',
                    metadata=WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id="cover-media",
                    cached_body_images={cached_entry.source_url_sha256: cached_entry},
                )
            )

        self.assertEqual(seen_paths.count("/cgi-bin/media/uploadimg"), 0)
        self.assertEqual(result.body_image_cache_entries[0].source_url_sha256, WeChatOfficialAccountClient.body_image_source_sha256(source))

    def test_replaces_hidden_background_image_and_img_with_the_same_wechat_url(self) -> None:
        source = "https://images.example.com/avatar.png"
        client = WeChatOfficialAccountClient()
        client._upload_article_image = AsyncMock(return_value="https://mmbiz.qpic.cn/avatar.png")  # type: ignore[method-assign]
        html = (
            f'<section style="width: 7em; height: 7em; border-radius: 100%; background-image: url(\'{source}\'); overflow: hidden;">'
            f'<img src="{source}" style="width: 100%; height: 100%; opacity: 0;">'
            "</section>"
        )

        result = asyncio.run(
            client._replace_body_images(
                MagicMock(),
                "token",
                html,
                local_image_loader=lambda _: (b"avatar", "image/png", "avatar.png"),
            )
        )

        image = BeautifulSoup(result.html, "html.parser").find("img")
        container = BeautifulSoup(result.html, "html.parser").find("section")
        assert image is not None
        assert container is not None
        self.assertEqual(image.get("src"), "https://mmbiz.qpic.cn/avatar.png")
        self.assertEqual(image.get("style"), "width: 100%; height: 100%; opacity: 0;")
        self.assertIn("background-image: url('https://mmbiz.qpic.cn/avatar.png')", container.get("style") or "")
        client._upload_article_image.assert_awaited_once()

    def test_replaces_svg_image_href_and_legacy_xlink_href(self) -> None:
        primary = "https://images.example.com/graphic-primary.png"
        fallback = "https://images.example.com/graphic-fallback.png"
        client = WeChatOfficialAccountClient()
        client._upload_article_image = AsyncMock(side_effect=[
            "https://mmbiz.qpic.cn/graphic-primary.png",
            "https://mmbiz.qpic.cn/graphic-fallback.png",
        ])  # type: ignore[method-assign]

        result = asyncio.run(
            client._replace_body_images(
                MagicMock(),
                "token",
                (
                    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                    f'<image href="{primary}"/><image xlink:href="{fallback}"/>'
                    "</svg>"
                ),
                local_image_loader=lambda source: (source.encode("utf-8"), "image/png", source.rsplit("/", 1)[-1]),
            )
        )

        self.assertEqual(
            WeChatOfficialAccountClient.body_image_sources(result.html),
            ["https://mmbiz.qpic.cn/graphic-primary.png", "https://mmbiz.qpic.cn/graphic-fallback.png"],
        )
        soup = BeautifulSoup(result.html, "html.parser")
        images = soup.find_all("image")
        self.assertEqual(images[0].get("href"), "https://mmbiz.qpic.cn/graphic-primary.png")
        self.assertEqual(images[1].get("xlink:href"), "https://mmbiz.qpic.cn/graphic-fallback.png")
        self.assertEqual(client._upload_article_image.await_count, 2)

    def test_replaces_srcset_and_background_shorthand_images(self) -> None:
        primary = "/api/documents/local-images/primary.png"
        alternate = "/api/documents/local-images/alternate.png"
        background = "/api/documents/local-images/background.png"
        client = WeChatOfficialAccountClient()
        client._upload_article_image = AsyncMock(side_effect=[
            "https://mmbiz.qpic.cn/primary.png",
            "https://mmbiz.qpic.cn/alternate.png",
            "https://mmbiz.qpic.cn/background.png",
        ])  # type: ignore[method-assign]

        result = asyncio.run(
            client._replace_body_images(
                MagicMock(),
                "token",
                f'<section style="background:url({background})"><img src="{primary}" srcset="{primary} 1x, {alternate} 2x"></section>',
                local_image_loader=lambda source: (source.encode("utf-8"), "image/png", source.rsplit("/", 1)[-1]),
            )
        )

        soup = BeautifulSoup(result.html, "html.parser")
        image = soup.find("img")
        section = soup.find("section")
        assert image is not None
        assert section is not None
        self.assertEqual(image.get("src"), "https://mmbiz.qpic.cn/primary.png")
        self.assertEqual(
            image.get("srcset"),
            "https://mmbiz.qpic.cn/primary.png 1x, https://mmbiz.qpic.cn/alternate.png 2x",
        )
        self.assertIn("https://mmbiz.qpic.cn/background.png", section.get("style") or "")
        self.assertEqual(client._upload_article_image.await_count, 3)

    def test_reuploads_cached_body_image_once_when_wechat_rejects_its_url(self) -> None:
        source = "https://images.example.com/cached.png"
        source_hash = WeChatOfficialAccountClient.body_image_source_sha256(source)
        cached_entry = BodyImageCacheEntry(source_hash, "a" * 64, "image/png", "https://mmbiz.qpic.cn/stale.png", "uploadimg")
        seen_paths: list[str] = []
        draft_attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal draft_attempts
            seen_paths.append(request.url.path)
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            if request.url.host == "images.example.com":
                return httpx.Response(200, headers={"content-type": "image/png"}, content=b"fresh-image")
            if request.url.path == "/cgi-bin/media/uploadimg":
                return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/fresh.png"})
            if request.url.path == "/cgi-bin/draft/add":
                draft_attempts += 1
                body = json.loads(request.content)
                if draft_attempts == 1:
                    self.assertIn("stale.png", body["articles"][0]["content"])
                    return httpx.Response(200, json={"errcode": 47001, "errmsg": "data format error"})
                self.assertIn("fresh.png", body["articles"][0]["content"])
                return httpx.Response(200, json={"media_id": "draft-media"})
            raise AssertionError(f"unexpected request {request.url}")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ), patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            result = asyncio.run(
                WeChatOfficialAccountClient().create_draft(
                    self.account,
                    html=f'<p><img src="{source}"></p>',
                    metadata=WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id="cover-media",
                    cached_body_images={source_hash: cached_entry},
                )
            )

        self.assertEqual(result.media_id, "draft-media")
        self.assertEqual(draft_attempts, 2)
        self.assertEqual(seen_paths.count("/cgi-bin/media/uploadimg"), 1)
        self.assertEqual(result.body_image_cache_entries[0].wechat_url, "https://mmbiz.qpic.cn/fresh.png")

    def test_auto_update_creates_a_new_draft_after_wechat_rejects_the_target_media_id(self) -> None:
        seen_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            if request.url.path == "/cgi-bin/draft/update":
                self.assertEqual(json.loads(request.content)["media_id"], "deleted-media")
                return httpx.Response(200, json={"errcode": 40007, "errmsg": "invalid media_id"})
            if request.url.path == "/cgi-bin/draft/add":
                return httpx.Response(200, json={"media_id": "new-media"})
            raise AssertionError(f"unexpected request {request.url}")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            result = asyncio.run(
                WeChatOfficialAccountClient().update_draft(
                    self.account,
                    target_media_id="deleted-media",
                    html="<p>正文</p>",
                    metadata=WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id="cover-media",
                    fallback_to_create_on_invalid_target=True,
                )
            )

        self.assertEqual(result.media_id, "new-media")
        self.assertTrue(result.created_new_draft)
        self.assertEqual(seen_paths.count("/cgi-bin/draft/update"), 1)
        self.assertEqual(seen_paths.count("/cgi-bin/draft/add"), 1)

    def test_invalid_draft_input_does_not_call_wechat(self) -> None:
        with patch("app.services.wechat_official_account.httpx.AsyncClient") as async_client:
            with self.assertRaises(WeChatApiError):
                asyncio.run(
                    WeChatOfficialAccountClient().create_draft(
                        self.account,
                        html="<p>正文</p>",
                        metadata=WeChatArticleMetadata(title=""),
                        cover=CoverImage(b"cover", "image/png", "cover.png"),
                        cached_cover_media_id=None,
                    )
                )
        async_client.assert_not_called()

    def test_preserves_wechat_native_link_markup_before_submitting_draft(self) -> None:
        submitted_content = ""

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal submitted_content
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            if request.url.path == "/cgi-bin/draft/add":
                submitted_content = json.loads(request.content)["articles"][0]["content"]
                return httpx.Response(200, json={"media_id": "draft-media"})
            raise AssertionError(f"unexpected request {request.url}")

        source_html = (
            '<p style="font-size:13px;color:#555;line-height:1.8;margin:8px 0 0 0;">'
            '<a class="weapp_text_link" data-miniprogram-appid="wxc8dc2d3cafab889e" '
            'data-miniprogram-path="/pages/koc/kl?fid=734952377437786112" '
            'data-miniprogram-nickname="文助手" href="https://idocx.cc/" style="font-size:15px;">'
            '易路同行 耕耘不辍.docx</a></p>'
        )
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            asyncio.run(
                WeChatOfficialAccountClient().create_draft(
                    self.account,
                    html=source_html,
                    metadata=WeChatArticleMetadata(title="标题", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id="cover-media",
                )
            )

        link = BeautifulSoup(submitted_content, "html.parser").find("a")
        assert link is not None
        self.assertEqual(link.get("href"), "https://idocx.cc/")
        self.assertIn("weapp_text_link", link.get("class") or [])
        self.assertEqual(link.get("data-miniprogram-appid"), "wxc8dc2d3cafab889e")
        self.assertEqual(link.get("data-miniprogram-path"), "/pages/koc/kl?fid=734952377437786112")
        self.assertEqual(link.get("data-miniprogram-nickname"), "文助手")
        self.assertIn("font-size:15px", link.get("style") or "")

    def test_lists_targets_and_updates_existing_draft(self) -> None:
        seen_update_payload: dict[str, object] | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal seen_update_payload
            if request.url.path == "/cgi-bin/stable_token":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            if request.url.path == "/cgi-bin/draft/batchget":
                self.assertEqual(json.loads(request.content), {"offset": 0, "count": 20, "no_content": 1})
                return httpx.Response(
                    200,
                    json={
                        "total_count": 1,
                        "item": [{
                            "media_id": "target-media",
                            "update_time": 1_700_000_000,
                            "content": {"news_item": [{"title": "原草稿"}, {"title": "第二篇"}]},
                        }],
                    },
                )
            if request.url.path == "/cgi-bin/draft/get":
                self.assertEqual(json.loads(request.content), {"media_id": "target-media"})
                return httpx.Response(200, json={"news_item": [{"title": "原草稿"}, {"title": "第二篇"}]})
            if request.url.host == "images.example.com":
                return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")
            if request.url.path == "/cgi-bin/media/uploadimg":
                return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/temporary-body.png"})
            if request.url.path == "/cgi-bin/material/add_material":
                return httpx.Response(200, json={"media_id": "cover-media", "url": "https://mmbiz.qpic.cn/body.png"})
            if request.url.path == "/cgi-bin/draft/update":
                seen_update_payload = json.loads(request.content)
                return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
            raise AssertionError(f"unexpected request {request.url}")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.wechat_official_account.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ), patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
            asyncio.run(WeChatOfficialAccountClient.clear_token_cache())
            client = WeChatOfficialAccountClient()
            targets = asyncio.run(client.list_draft_targets(self.account))
            self.assertEqual(targets, [DraftTarget("target-media", "原草稿", 1_700_000_000, 2)])
            target = asyncio.run(client.validate_draft_target(self.account, "target-media"))
            self.assertEqual(target, DraftTarget("target-media", "原草稿", None, 2))
            result = asyncio.run(
                client.update_draft(
                    self.account,
                    target_media_id="target-media",
                    html='<p><img src="https://images.example.com/a.png"></p>',
                    metadata=WeChatArticleMetadata(title="新标题", cover_url="https://images.example.com/cover.png"),
                    cover=CoverImage(b"cover", "image/png", "cover.png"),
                    cached_cover_media_id=None,
                )
            )

        self.assertEqual(result.media_id, "target-media")
        self.assertEqual(seen_update_payload and seen_update_payload["media_id"], "target-media")
        self.assertEqual(seen_update_payload and seen_update_payload["index"], 0)
        self.assertIsInstance((seen_update_payload or {})["articles"], dict)
        self.assertEqual((seen_update_payload or {})["articles"]["title"], "新标题")
        self.assertIn("temporary-body.png", str((seen_update_payload or {})["articles"]))

    def test_trusted_oss_benchmark_address_is_narrowly_allowed(self) -> None:
        hostname = "bucket.oss-cn-chengdu.aliyuncs.com"
        self.assertTrue(
            WeChatOfficialAccountClient._is_trusted_oss_benchmark_address(
                hostname, ipaddress.ip_address("198.18.1.52"), {hostname}
            )
        )
        self.assertFalse(
            WeChatOfficialAccountClient._is_trusted_oss_benchmark_address(
                "other.example.com", ipaddress.ip_address("198.18.1.52"), {hostname}
            )
        )
        self.assertFalse(
            WeChatOfficialAccountClient._is_trusted_oss_benchmark_address(
                hostname, ipaddress.ip_address("10.0.0.1"), {hostname}
            )
        )

    def test_large_image_payload_spools_to_disk_and_closes(self) -> None:
        payload = ImagePayload.from_bytes(
            b"x" * (1024 * 1024 + 1),
            content_type="image/png",
            filename="large.png",
        )
        try:
            self.assertTrue(payload.is_file_backed)
            self.assertEqual(payload.size, 1024 * 1024 + 1)
            self.assertEqual(payload.content_sha256, hashlib.sha256(b"x" * (1024 * 1024 + 1)).hexdigest())
            self.assertEqual(len(payload.read_bytes()), payload.size)
        finally:
            payload.close()
        self.assertTrue(payload._stream.closed)

    def test_remote_large_image_download_uses_spooled_payload(self) -> None:
        data = b"y" * (1024 * 1024 + 1)
        client = WeChatOfficialAccountClient()
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=data)
        )

        async def download() -> ImagePayload:
            async with httpx.AsyncClient(transport=transport) as http_client:
                with patch.object(WeChatOfficialAccountClient, "_validate_public_url", new=AsyncMock()):
                    return await client._download_image(
                        http_client,
                        "https://images.example.com/large.png",
                        allowed_types={"image/png"},
                        max_bytes=10 * 1024 * 1024,
                        label="正文图片",
                    )

        payload = asyncio.run(download())
        try:
            self.assertTrue(payload.is_file_backed)
            self.assertEqual(payload.filename, "large.png")
            self.assertEqual(payload.content_sha256, hashlib.sha256(data).hexdigest())
        finally:
            payload.close()

    def test_body_image_closes_spooled_payload_after_upload_failure(self) -> None:
        payload = ImagePayload.from_bytes(
            b"z" * (1024 * 1024 + 1),
            content_type="image/png",
            filename="large.png",
        )
        client = WeChatOfficialAccountClient()
        client._upload_permanent_image = AsyncMock(side_effect=WeChatApiError("上传失败"))  # type: ignore[method-assign]
        with self.assertRaisesRegex(WeChatApiError, "上传失败"):
            asyncio.run(
                client._replace_body_images(
                    MagicMock(),
                    "token",
                    '<p><img src="https://images.example.com/large.png"></p>',
                    local_image_loader=lambda _: payload,
                )
            )
        self.assertTrue(payload._stream.closed)

    def test_redacts_credential_values_from_transport_messages(self) -> None:
        rendered = _redact_sensitive_text(
            "GET https://api.weixin.qq.com/cgi-bin/draft/add?access_token=token-secret&signature=signed-value "
            "api_key=provider-secret {\"app_secret\":\"app-secret\"}"
        )
        self.assertNotIn("token-secret", rendered)
        self.assertNotIn("signed-value", rendered)
        self.assertNotIn("provider-secret", rendered)
        self.assertNotIn("app-secret", rendered)
        self.assertEqual(rendered.count("[REDACTED]"), 4)


if __name__ == "__main__":
    unittest.main()
