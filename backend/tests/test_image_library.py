import asyncio
import io
import unittest
from datetime import datetime, timezone
from html import escape, unescape
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.routes.image_library import (
    bulk_delete_image_library_assets,
    delete_image_library_asset,
    import_searched_image,
    list_image_library_assets,
    set_image_library_asset_as_cover,
    update_image_library_asset,
    update_image_library_settings,
    upload_image_library_assets,
)
from app.api.routes.image_generations import delete_document_generated_image
from app.db.base import Base
from app.models.ai_image_model import AIImageModel
from app.models.ai_provider import AIProvider, ProviderType
from app.models.document import Document, DocumentSourceType
from app.models.document_import import DocumentImport, DocumentImportAsset, DocumentImportStatus
from app.models.image_generation import (
    GeneratedImageAsset,
    ImageGeneration,
    ImageGenerationPurpose,
    ImageGenerationSource,
    ImageGenerationStatus,
    ImageLibraryAsset,
    ImageLibraryMode,
    ImageLibrarySettings,
    ImageLibrarySource,
)
from app.models.storage_config import StorageConfig
from app.models.user import User, UserRole
from app.schemas.image_library import (
    ImageLibraryAssetRead,
    ImageLibraryAssetUpdate,
    ImageLibraryBulkDelete,
    ImageLibraryCoverApply,
    ImageLibrarySearchImport,
    ImageLibrarySettingsUpdate,
)
from app.services.document_images import StoredDocumentImage
from app.services.image_generation import generation_payload
from app.services.image_library import asset_payload, backfill_generated_assets, backfill_imported_assets


class ImageLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.admin = self._user("admin", UserRole.ADMIN)
        self.owner = self._user("owner")
        self.other = self._user("other")
        self.owner_document = self._document(self.owner, "所有者文章")
        self.other_document = self._document(self.other, "其他用户文章")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _user(self, username: str, role: UserRole = UserRole.USER) -> User:
        user = User(
            username=username,
            display_name=username,
            password_hash="not-used",
            role=role,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def _document(self, user: User, title: str) -> Document:
        document = Document(
            owner_id=user.id,
            created_by_id=user.id,
            last_modified_by_id=user.id,
            title=title,
            current_html="<p>正文</p>",
        )
        self.db.add(document)
        self.db.commit()
        return document

    def _asset(
        self,
        owner: User,
        name: str,
        *,
        source: ImageLibrarySource = ImageLibrarySource.UPLOAD,
        shared: bool = False,
        generated_asset_id: str = "",
    ) -> ImageLibraryAsset:
        slug = f"{owner.id}-{name}-{len(self.db.query(ImageLibraryAsset).all())}"
        asset = ImageLibraryAsset(
            id=f"asset-{slug}",
            owner_id=owner.id,
            document_id=self.owner_document.id if owner.id == self.owner.id else self.other_document.id,
            name=name,
            source=source,
            object_key=f"local/images/{slug}.png",
            storage_mode="local",
            url=f"/api/documents/local-images/{slug}.png",
            content_type="image/png",
            size=24,
            width=1,
            height=1,
            is_shared=shared,
            generated_asset_id=generated_asset_id,
        )
        self.db.add(asset)
        self.db.commit()
        return asset

    def _list(self, user: User) -> dict:
        return list_image_library_assets(
            q="",
            source="all",
            page=1,
            page_size=100,
            current_user=user,
            db=self.db,
        )

    def _temporary_import_asset(self, name: str, *, with_import: bool = False) -> ImageLibraryAsset:
        asset = self._asset(self.owner, name)
        asset.object_key = f"yibanpaiban/direct-imports/{name}.png"
        asset.storage_mode = "oss"
        asset.url = f"https://storage.example/{asset.object_key}"
        self.owner_document.current_html += f'<img src="{asset.url}" data-original="{asset.url}">'
        if self.db.get(StorageConfig, 1) is None:
            self.db.add(StorageConfig(id=1, endpoint="https://storage.example", bucket="images"))
        if with_import:
            self.db.add(DocumentImport(
                id=name, owner_id=self.owner.id, document_id=self.owner_document.id,
                source_type=DocumentSourceType.PDF, source_filename="source.pdf",
                source_content_type="application/pdf", source_size=1,
                source_object_key=f"source/{name}.pdf", status=DocumentImportStatus.COMPLETED,
                expires_at=datetime.now(timezone.utc),
            ))
            self.db.flush()
            self.db.add(DocumentImportAsset(
                id=name, import_id=name, client_id=name, filename=f"{name}.png",
                content_type="image/png", size=24, object_key=asset.object_key,
            ))
        self.db.commit()
        return asset

    def _assert_import_promotion_persists(self, *, autoflush: bool, with_import: bool) -> None:
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        name = "promotion"
        asset = self._temporary_import_asset(name, with_import=with_import)
        asset_id, document_id, old_url = asset.id, asset.document_id, asset.url
        self.db.close()
        stored = StoredDocumentImage(
            url=f"https://storage.example/images/{name}.png",
            object_key=f"images/{name}.png", storage_mode="oss",
        )
        with (
            patch("app.services.image_library.oss_client.get_object_bytes", return_value=png) as download,
            patch("app.services.image_library.store_tracked_document_image", return_value=stored) as upload,
        ):
            with self.Session(autoflush=autoflush) as migration_db:
                count = backfill_imported_assets(migration_db)
            with self.Session(autoflush=autoflush) as verification_db:
                saved = verification_db.get(ImageLibraryAsset, asset_id)
                self.assertEqual(saved.object_key, stored.object_key)
                self.assertEqual(saved.url, stored.url)
                self.assertEqual((saved.width, saved.height, saved.size), (1, 1, len(png)))
                html = verification_db.get(Document, document_id).current_html
                self.assertNotIn(old_url, html)
                self.assertIn(f'data-original="{stored.url}"', html)
                self.assertEqual(count, 1)
                self.assertEqual(backfill_imported_assets(verification_db), 0)
            download.assert_called_once()
            upload.assert_called_once()

    def test_import_promotion_without_new_imports_is_persisted(self) -> None:
        self._assert_import_promotion_persists(autoflush=False, with_import=False)

    def test_import_promotion_with_existing_import_is_persisted(self) -> None:
        self._assert_import_promotion_persists(autoflush=False, with_import=True)

    def test_import_promotion_without_new_imports_is_persisted_with_autoflush(self) -> None:
        self._assert_import_promotion_persists(autoflush=True, with_import=False)

    def test_import_promotion_with_existing_import_is_persisted_with_autoflush(self) -> None:
        self._assert_import_promotion_persists(autoflush=True, with_import=True)

    def test_failed_import_promotion_remains_retryable(self) -> None:
        asset = self._temporary_import_asset("retry")
        asset_id, old_key, document_id = asset.id, asset.object_key, asset.document_id
        old_html = self.owner_document.current_html
        stored = StoredDocumentImage("https://storage.example/images/retry.png", "images/retry.png", "oss")
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        with (
            patch("app.services.image_library.oss_client.get_object_bytes", side_effect=[OSError("unavailable"), png]) as download,
            patch("app.services.image_library.store_tracked_document_image", return_value=stored) as upload,
        ):
            with self.Session(autoflush=False) as migration_db:
                self.assertEqual(backfill_imported_assets(migration_db), 0)
            with self.Session(autoflush=False) as migration_db:
                self.assertEqual(migration_db.get(ImageLibraryAsset, asset_id).object_key, old_key)
                self.assertEqual(migration_db.get(Document, document_id).current_html, old_html)
                upload.assert_not_called()
                self.assertEqual(backfill_imported_assets(migration_db), 1)
            with self.Session(autoflush=False) as migration_db:
                self.assertEqual(migration_db.get(ImageLibraryAsset, asset_id).object_key, stored.object_key)
                self.assertEqual(backfill_imported_assets(migration_db), 0)
            self.assertEqual(download.call_count, 2)
            upload.assert_called_once()

    def _assert_escaped_import_urls_promoted(self, *, registered: bool) -> None:
        asset = self._temporary_import_asset("escaped", with_import=True)
        document_id = asset.document_id
        old_key = asset.object_key
        # The HTML URL may have been refreshed independently of the gallery.
        html_url = asset.url + "?expires=2&signature=refreshed"
        asset.url += "?expires=1&signature=original"
        self.owner_document.current_html = f'<img src="{escape(html_url)}" data-original="{escape(html_url)}">'
        if not registered:
            self.db.delete(asset)
        self.db.commit()
        self.db.close()
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        stored = StoredDocumentImage(
            "https://storage.example/images/escaped.png?expires=3&signature=durable", "images/escaped.png", "oss",
        )
        with (
            patch("app.services.image_library.oss_client.get_object_bytes", return_value=png) as download,
            patch("app.services.image_library.oss_client.sign_read_url", return_value=html_url),
            patch("app.services.image_library.store_tracked_document_image", return_value=stored) as upload,
        ):
            with self.Session(autoflush=False) as migration_db:
                self.assertEqual(backfill_imported_assets(migration_db), 1)
            with self.Session(autoflush=False) as verification_db:
                saved = verification_db.query(ImageLibraryAsset).one()
                self.assertEqual(saved.object_key, stored.object_key)
                html = verification_db.get(Document, document_id).current_html
                self.assertNotIn(old_key, html)
                self.assertIn(f'src="{stored.url}"', unescape(html))
                self.assertIn(f'data-original="{stored.url}"', unescape(html))
                self.assertEqual(backfill_imported_assets(verification_db), 0)
                self.assertEqual(verification_db.query(ImageLibraryAsset).count(), 1)
            download.assert_called_once()
            upload.assert_called_once()

    def test_escaped_import_urls_are_replaced_without_duplicate_registration(self) -> None:
        self._assert_escaped_import_urls_promoted(registered=True)

    def test_new_import_registration_promotes_images_in_the_same_pass(self) -> None:
        self._assert_escaped_import_urls_promoted(registered=False)

    def test_personal_mode_is_cross_document_but_owner_isolated(self) -> None:
        own = self._asset(self.owner, "个人图片")
        self._asset(self.other, "他人图片")

        result = self._list(self.owner)

        self.assertEqual(result["mode"], "personal")
        self.assertEqual([item["id"] for item in result["items"]], [own.id])
        self.assertTrue(result["items"][0]["can_manage"])

    def test_admin_selected_shared_assets_are_visible_and_manageable_by_everyone(self) -> None:
        shared = self._asset(self.owner, "允许公开")
        private = self._asset(self.owner, "保持私有")
        update_image_library_settings(
            ImageLibrarySettingsUpdate(mode="shared", shared_asset_ids=[shared.id]),
            self.admin,
            self.db,
        )

        result = self._list(self.other)
        self.assertEqual([item["id"] for item in result["items"]], [shared.id])
        self.assertTrue(result["items"][0]["can_manage"])

        update_image_library_asset(
            shared.id,
            ImageLibraryAssetUpdate(name="共享重命名"),
            self.other,
            self.db,
        )
        self.db.refresh(shared)
        self.assertEqual(shared.name, "共享重命名")

        with self.assertRaises(HTTPException) as context:
            update_image_library_asset(
                private.id,
                ImageLibraryAssetUpdate(name="不可见"),
                self.other,
                self.db,
            )
        self.assertEqual(context.exception.status_code, 404)

    def test_switching_back_to_personal_preserves_shared_selection(self) -> None:
        shared = self._asset(self.owner, "保留共享标记")
        update_image_library_settings(
            ImageLibrarySettingsUpdate(mode="shared", shared_asset_ids=[shared.id]),
            self.admin,
            self.db,
        )
        update_image_library_settings(
            ImageLibrarySettingsUpdate(mode="personal", shared_asset_ids=[]),
            self.admin,
            self.db,
        )
        self.db.refresh(shared)

        self.assertTrue(shared.is_shared)
        self.assertEqual(self._list(self.owner)["total"], 1)
        self.assertEqual(self._list(self.other)["total"], 0)

    def test_shared_mode_new_assets_are_shared_and_soft_delete_keeps_object_metadata(self) -> None:
        self.db.add(ImageLibrarySettings(id=1, mode=ImageLibraryMode.SHARED, updated_by_id=self.admin.id))
        self.db.commit()
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01\x00\x00\x00\x01"
        upload = UploadFile(filename="shared.png", file=io.BytesIO(png))
        stored = StoredDocumentImage(
            url="/api/documents/local-images/shared.png",
            object_key="local/images/shared.png",
            storage_mode="local",
        )
        with patch("app.api.routes.image_library.store_tracked_document_image", return_value=stored):
            payload = asyncio.run(upload_image_library_assets([upload], self.owner_document.id, self.owner, self.db))

        asset = self.db.get(ImageLibraryAsset, payload[0]["id"])
        self.assertIsNotNone(asset)
        self.assertTrue(asset.is_shared)
        delete_image_library_asset(asset.id, self.other, self.db)
        self.db.refresh(asset)
        self.assertIsNotNone(asset.deleted_at)
        self.assertEqual(asset.object_key, stored.object_key)
        self.assertEqual(asset.url, stored.url)

    def test_upload_rejects_unsupported_content_and_oversized_file(self) -> None:
        invalid = UploadFile(filename="bad.svg", file=io.BytesIO(b"<svg></svg>"))
        with self.assertRaises(HTTPException) as invalid_context:
            asyncio.run(upload_image_library_assets([invalid], self.owner_document.id, self.owner, self.db))
        self.assertEqual(invalid_context.exception.status_code, 422)

        oversized = UploadFile(filename="large.png", file=io.BytesIO(b"12345"))
        with patch("app.api.routes.image_library.MAX_DOCUMENT_IMAGE_BYTES", 4):
            with self.assertRaises(HTTPException) as oversized_context:
                asyncio.run(upload_image_library_assets([oversized], self.owner_document.id, self.owner, self.db))
        self.assertEqual(oversized_context.exception.status_code, 413)

    def test_upload_accepts_one_hundred_images_in_order(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01\x00\x00\x00\x01"
        uploads = [UploadFile(filename=f"photo-{i}.png", file=io.BytesIO(png)) for i in range(100)]
        def store(_db, _data, filename):
            return StoredDocumentImage(url=f"/api/documents/local-images/{filename}", object_key=f"local/images/{filename}", storage_mode="local")
        with patch("app.api.routes.image_library.store_tracked_document_image", side_effect=store) as stored:
            payload = asyncio.run(upload_image_library_assets(uploads, self.owner_document.id, self.owner, self.db))
        self.assertEqual(len(payload), 100)
        self.assertEqual([item["name"] for item in payload], [f"photo-{i}.png" for i in range(100)])
        self.assertEqual(stored.call_count, 100)
        self.assertTrue(all(upload.file.closed for upload in uploads))

    def test_upload_rejects_one_hundred_and_one_before_storing_any_image(self) -> None:
        uploads = [UploadFile(filename=f"photo-{i}.png", file=io.BytesIO(b"pixels")) for i in range(101)]
        with patch("app.api.routes.image_library.store_tracked_document_image", side_effect=AssertionError("rejected batch")):
            with self.assertRaises(HTTPException) as rejected:
                asyncio.run(upload_image_library_assets(uploads, self.owner_document.id, self.owner, self.db))
        self.assertEqual(rejected.exception.status_code, 422)
        self.assertIn("100", rejected.exception.detail)
        self.assertEqual(self.db.query(ImageLibraryAsset).count(), 0)
        self.assertTrue(all(upload.file.closed for upload in uploads))

    def test_bulk_delete_is_atomic_when_one_asset_is_not_visible(self) -> None:
        own = self._asset(self.owner, "自己的")
        hidden = self._asset(self.other, "别人的")

        with self.assertRaises(HTTPException) as context:
            bulk_delete_image_library_assets(
                ImageLibraryBulkDelete(asset_ids=[own.id, hidden.id]),
                self.owner,
                self.db,
            )

        self.assertEqual(context.exception.status_code, 404)
        self.db.refresh(own)
        self.assertIsNone(own.deleted_at)

    def test_any_shared_asset_can_be_cover_and_clears_crop_parameters(self) -> None:
        asset = self._asset(self.owner, "共享封面", shared=True)
        self.db.add(ImageLibrarySettings(id=1, mode=ImageLibraryMode.SHARED, updated_by_id=self.admin.id))
        self.other_document.wechat_pic_crop_235_1 = "old-wide"
        self.other_document.wechat_pic_crop_1_1 = "old-square"
        self.db.commit()

        result = set_image_library_asset_as_cover(
            asset.id,
            ImageLibraryCoverApply(document_id=self.other_document.id),
            self.other,
            self.db,
        )
        self.db.refresh(self.other_document)

        self.assertEqual(self.other_document.wechat_cover_url, asset.url)
        self.assertEqual(self.other_document.wechat_pic_crop_235_1, "")
        self.assertEqual(self.other_document.wechat_pic_crop_1_1, "")
        self.assertEqual(result["id"], asset.id)
        self.assertEqual(len(self.other_document.versions), 1)

    def test_legacy_asset_without_updated_at_uses_created_at_in_response(self) -> None:
        asset = self._asset(self.owner, "旧素材")
        asset.__dict__["updated_at"] = None

        payload = asset_payload(self.db, asset, self.owner)
        validated = ImageLibraryAssetRead.model_validate(payload)

        self.assertEqual(validated.updated_at, validated.created_at)

    def test_oss_asset_urls_are_reused_during_gallery_refreshes(self) -> None:
        storage = StorageConfig(
            endpoint="oss.example.test",
            bucket="images",
            access_key_id="key",
            access_key_secret_encrypted="encrypted-secret",
        )
        asset = self._asset(self.owner, "OSS 图片")
        asset.storage_mode = "oss"
        asset.object_key = "yibanpaiban/gallery.png"
        self.db.add(storage)
        self.db.commit()

        with patch("app.services.image_library.oss_client.sign_read_url", return_value="https://oss.example.test/gallery.png?signature=stable") as sign_url:
            first = asset_payload(self.db, asset, self.owner)
            second = asset_payload(self.db, asset, self.owner)

        self.assertEqual(first["url"], second["url"])
        sign_url.assert_called_once()

    def test_search_candidate_is_imported_only_when_route_is_applied(self) -> None:
        candidate = SimpleNamespace(id="candidate", title="搜索结果")
        image = SimpleNamespace(content_type="image/png", width=1, height=1)
        stored = StoredDocumentImage(
            url="/api/documents/local-images/search.png",
            object_key="local/images/search.png",
            storage_mode="local",
        )
        with (
            patch("app.api.routes.image_library.decode_candidate_token", return_value=candidate),
            patch("app.api.routes.image_library.fetch_candidate_image", new=AsyncMock(return_value=(b"png", image))),
            patch("app.api.routes.image_library.store_tracked_document_image", return_value=stored),
        ):
            result = asyncio.run(import_searched_image(
                ImageLibrarySearchImport(document_id=self.owner_document.id, candidate_token="signed-token"),
                self.owner,
                self.db,
            ))

        asset = self.db.get(ImageLibraryAsset, result["id"])
        self.assertEqual(asset.source, ImageLibrarySource.SEARCH)
        self.assertEqual(asset.document_id, self.owner_document.id)

    def test_generated_assets_backfill_once_and_payload_links_library_asset(self) -> None:
        provider = AIProvider(
            name="provider",
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            base_url="https://example.test/v1",
            image_protocol="openai_images",
            image_base_url="https://example.test/v1/images",
            api_key_encrypted="key",
        )
        model = AIImageModel(
            provider=provider,
            model_name="image-model",
            display_name="图片模型",
            supported_aspect_ratios=["landscape"],
            supported_qualities=["auto"],
        )
        generation = ImageGeneration(
            id="generation-1",
            document_id=self.owner_document.id,
            model=model,
            user_id=self.owner.id,
            source=ImageGenerationSource.EDITOR,
            purpose=ImageGenerationPurpose.BODY,
            prompt="一张图片",
            quantity=1,
            aspect_ratio="landscape",
            quality="auto",
            status=ImageGenerationStatus.SUCCEEDED,
        )
        generated = GeneratedImageAsset(
            id="generated-1",
            generation=generation,
            object_key="local/images/generated.png",
            storage_mode="local",
            url="/api/documents/local-images/generated.png",
            content_type="image/png",
            size=24,
            width=1,
            height=1,
        )
        self.db.add_all([provider, model, generation, generated])
        self.db.commit()

        self.assertEqual(backfill_generated_assets(self.db), 1)
        self.assertEqual(backfill_generated_assets(self.db), 0)
        library = self.db.query(ImageLibraryAsset).filter_by(generated_asset_id=generated.id).one()
        self.assertFalse(library.is_shared)
        payload = generation_payload(generation)
        self.assertEqual(payload["assets"][0]["library_asset_id"], library.id)
        self.assertEqual(payload["assets"][0]["library_url"], library.url)

        with patch("app.api.routes.image_generations.delete_tracked_document_image") as delete_object:
            with self.assertRaises(HTTPException) as context:
                delete_document_generated_image(
                    self.owner_document.id,
                    generation.id,
                    generated.id,
                    self.owner,
                    self.db,
                )
        self.assertEqual(context.exception.status_code, 409)
        delete_object.assert_not_called()
        self.assertIsNotNone(self.db.get(GeneratedImageAsset, generated.id))

        delete_image_library_asset(library.id, self.owner, self.db)
        self.assertIsNotNone(self.db.get(GeneratedImageAsset, generated.id))
        self.assertEqual(self.db.get(GeneratedImageAsset, generated.id).object_key, generated.object_key)


if __name__ == "__main__":
    unittest.main()
