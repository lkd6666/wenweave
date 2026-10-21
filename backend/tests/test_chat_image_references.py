import asyncio
import base64
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes.image_library import reference_image_library_asset, reference_image_library_assets
from app.db.base import Base
from app.models.chat_image_attachment import ChatImageAttachment
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_context_event import ChatContextEvent, ContextEventKind
from app.models.chat_session import ChatSession
from app.models.document import Document, DocumentSourceType
from app.models.document_visibility import VisibilityMode
from app.models.image_generation import ImageLibraryAsset, ImageLibraryMode, ImageLibrarySource
from app.models.user import User
from app.schemas.chat_images import ChatImageLibraryReference, ChatImageLibraryBatchReference
from app.services import local_uploads
from app.services.chat_images import chat_attachment_url, create_attachment, delete_attachment_object, image_content_blocks, read_attachment_bytes, user_message_content
from app.services.chat_agent import HtmlEditSession, _provider_message_tokens, run_agent_loop
from app.services.document_images import store_tracked_document_image
from app.services.image_library import create_library_asset, get_or_create_settings
from app.services.tool_output_store import ToolOutputStore


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


class AttachmentToolModel(BaseChatModel):
    requests: list[dict] = []
    patch_request: dict | None = None
    calls: int = 0

    @property
    def _llm_type(self):
        return "attachment-tools-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise NotImplementedError

    async def _astream(self, messages, **kwargs):
        index = self.calls
        self.calls += 1
        if index < len(self.requests):
            name, args = "import_chat_image", self.requests[index]
        elif index == len(self.requests) and self.patch_request:
            imported = next(message for message in reversed(messages) if isinstance(message, ToolMessage) and message.name == "import_chat_image")
            url = json.loads(imported.content)["url"]
            name = "apply_html_patch"
            args = json.loads(json.dumps(self.patch_request).replace("IMPORTED_URL", url))
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content="图片已处理"))
            return
        yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[{
            "name": name, "id": f"call-{index}", "args": json.dumps(args), "index": 0,
        }]))


class ImagePageToolModel(AttachmentToolModel):
    turns: list[list[BaseMessage]] = []
    tool_requests: list[dict | list[dict]] = []
    auto_page: bool = False
    include_image: bool = True
    page_size: int = 32

    async def _astream(self, messages, **kwargs):
        self.turns.append(list(messages))
        index = self.calls
        self.calls += 1
        if self.auto_page:
            page = next((json.loads(message.content) for message in reversed(messages) if isinstance(message, ToolMessage) and message.name == "view_chat_images_page"), None)
            if page is not None and (page.get("next_cursor") is None or page.get("blocked")):
                yield ChatGenerationChunk(message=AIMessageChunk(content="全部处理完成"))
                return
            request = {"name": "view_chat_images_page", "args": {
                "cursor": page["next_cursor"] if page else 0, "page_size": self.page_size,
                "include_image": self.include_image, "page_notes": "已查看上一页" if page else "",
            }}
        elif index < len(self.tool_requests):
            request = self.tool_requests[index]
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content="全部处理完成"))
            return
        batch = request if isinstance(request, list) else [request]
        for offset, call in enumerate(batch):
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[{
                **call, "args": json.dumps(call["args"]), "id": f"page-{index}-{offset}", "index": offset,
            }]))


class ImageLibraryChatReferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.storage_patch = patch.object(local_uploads, "LOCAL_UPLOAD_ROOT", Path(self.directory.name))
        self.storage_patch.start()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        self.owner = User(username="owner", password_hash="unused")
        self.other = User(username="other", password_hash="unused")
        self.db.add_all([self.owner, self.other])
        self.db.flush()
        self.document = Document(title="reference-test", owner_id=self.owner.id, source_type=DocumentSourceType.MARKDOWN)
        self.db.add(self.document)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.storage_patch.stop()
        self.directory.cleanup()

    def _asset(self, data=PNG, filename="photo.png", shared=False):
        image = local_uploads.inspect_image(data)
        asset = create_library_asset(
            self.db, owner_id=self.owner.id, name=filename, source=ImageLibrarySource.UPLOAD,
            stored=store_tracked_document_image(self.db, data, filename),
            content_type=image.content_type, size=len(data), width=image.width, height=image.height,
            is_shared=shared,
        )
        self.db.commit()
        return asset

    def _reference(self, asset, user=None):
        return reference_image_library_asset(
            asset.id, ChatImageLibraryReference(document_id=self.document.id), user or self.owner, self.db
        )

    def test_reference_reuses_pixels_without_reading_or_uploading(self):
        asset = self._asset()
        with patch("app.services.chat_images.read_attachment_bytes", side_effect=AssertionError("must not read")), \
                patch.object(local_uploads, "save_bytes", side_effect=AssertionError("must not upload")):
            result = self._reference(asset)
        attachment = self.db.get(ChatImageAttachment, result["id"])
        self.assertFalse(attachment.is_direct_input)
        self.assertEqual(attachment.object_key, asset.object_key)
        self.assertEqual(attachment.storage_mode, asset.storage_mode)
        self.assertEqual(read_attachment_bytes(self.db, attachment), PNG)
        self.assertIn("/chat-images/", result["preview_url"])
        self.assertIsNone(result["message_id"])
        delete_attachment_object(self.db, attachment)
        self.assertEqual(read_attachment_bytes(self.db, asset), PNG)

    def test_removing_reference_after_library_soft_delete_preserves_pixels(self):
        from app.services.image_library import soft_delete
        asset = self._asset()
        attachment = self.db.get(ChatImageAttachment, self._reference(asset)["id"])
        soft_delete(asset)
        self.db.commit()
        delete_attachment_object(self.db, attachment)
        self.db.delete(attachment)
        self.db.commit()
        self.assertEqual(read_attachment_bytes(self.db, asset), PNG)

    def test_generated_image_cannot_delete_pixels_referenced_by_chat(self):
        from app.api.routes.image_generations import delete_document_generated_image
        from app.services.image_library import soft_delete

        asset = self._asset()
        asset.generated_asset_id = "generated-image"
        self._reference(asset)
        soft_delete(asset)
        self.db.commit()
        generated = SimpleNamespace(id=asset.generated_asset_id, object_key=asset.object_key,
                                    storage_mode=asset.storage_mode, is_applied=False)
        with patch("app.api.routes.image_generations._generation_or_404", return_value=SimpleNamespace(assets=[generated])):
            with self.assertRaises(HTTPException) as denied:
                delete_document_generated_image(self.document.id, "generation", generated.id, self.owner, self.db)
        self.assertEqual(denied.exception.status_code, 409)
        self.assertEqual(read_attachment_bytes(self.db, asset), PNG)

    def _reference_many(self, ids):
        return reference_image_library_assets(
            ChatImageLibraryBatchReference(document_id=self.document.id, asset_ids=ids), self.owner, self.db
        )

    def test_batch_reference_preserves_selection_order_without_pixel_io(self):
        first = self._asset(filename="first.png")
        second = self._asset(filename="second.png")
        with patch("app.services.chat_images.read_attachment_bytes", side_effect=AssertionError("must not read")), \
                patch.object(local_uploads, "save_bytes", side_effect=AssertionError("must not upload")):
            results = self._reference_many([second.id, first.id])
        self.assertEqual([item["filename"] for item in results], ["second.png", "first.png"])
        self.assertEqual([self.db.get(ChatImageAttachment, item["id"]).object_key for item in results],
                         [second.object_key, first.object_key])

    def test_batch_references_one_hundred_images_without_reupload(self):
        assets = [self._asset(filename=f"file-{i}.png") for i in range(100)]
        with patch("app.services.chat_images.read_attachment_bytes", side_effect=AssertionError("must not read")), \
                patch.object(local_uploads, "save_bytes", side_effect=AssertionError("must not upload")):
            results = self._reference_many([asset.id for asset in reversed(assets)])
        self.assertEqual(len(results), 100)
        self.assertEqual(results[0]["filename"], "file-99.png")
        self.assertEqual(results[-1]["filename"], "file-0.png")

    def test_batch_checks_every_permission_before_creating_references(self):
        first = self._asset()
        second = self._asset()
        second.owner_id = self.other.id
        self.db.commit()
        with self.assertRaises(HTTPException) as denied:
            self._reference_many([first.id, second.id])
        self.assertEqual(denied.exception.status_code, 404)
        self.assertEqual(self.db.query(ChatImageAttachment).count(), 0)

    def test_batch_rolls_back_all_references_on_validation_or_commit_failure(self):
        first = self._asset()
        second = self._asset()
        second.size = 11 * 1024 * 1024
        self.db.commit()
        with self.assertRaises(HTTPException) as invalid:
            self._reference_many([first.id, second.id])
        self.assertEqual(invalid.exception.status_code, 400)
        self.assertEqual(self.db.query(ChatImageAttachment).count(), 0)
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(HTTPException) as failed:
                self._reference_many([first.id])
        self.assertEqual(failed.exception.status_code, 503)
        self.assertEqual(self.db.query(ChatImageAttachment).count(), 0)
        self.assertEqual(read_attachment_bytes(self.db, first), PNG)

    def test_batch_rejects_duplicate_ids(self):
        asset = self._asset()
        with self.assertRaises(HTTPException) as invalid:
            self._reference_many([asset.id, asset.id])
        self.assertEqual(invalid.exception.status_code, 422)
        self.assertEqual(self.db.query(ChatImageAttachment).count(), 0)

    def test_private_and_deleted_assets_cannot_be_referenced(self):
        asset = self._asset()
        with self.assertRaises(HTTPException) as denied:
            self._reference(asset, self.other)
        self.assertEqual(denied.exception.status_code, 404)
        from app.services.image_library import soft_delete
        soft_delete(asset)
        self.db.commit()
        with self.assertRaises(HTTPException) as deleted:
            self._reference(asset)
        self.assertEqual(deleted.exception.status_code, 404)
        self.assertEqual(self.db.query(ChatImageAttachment).count(), 0)

    def test_shared_asset_can_be_referenced_by_another_user(self):
        asset = self._asset(shared=True)
        get_or_create_settings(self.db).mode = ImageLibraryMode.SHARED
        self.db.commit()
        result = self._reference(asset, self.other)
        attachment = self.db.get(ChatImageAttachment, result["id"])
        self.assertEqual(attachment.uploader_id, self.other.id)
        self.assertEqual(attachment.document_id, self.document.id)
        self.assertEqual(read_attachment_bytes(self.db, attachment), PNG)

    def test_reference_requires_access_to_target_document(self):
        asset = self._asset(shared=True)
        get_or_create_settings(self.db).mode = ImageLibraryMode.SHARED
        self.document.visibility_mode = VisibilityMode.RESTRICTED
        self.document.allowed_users = [self.owner]
        self.db.commit()
        with self.assertRaises(HTTPException) as denied:
            self._reference(asset, self.other)
        self.assertEqual(denied.exception.status_code, 404)

    def test_bmp_library_image_is_converted_for_multimodal_input(self):
        output = io.BytesIO()
        Image.new("RGB", (2, 3), "red").save(output, format="BMP")
        asset = self._asset(output.getvalue(), "photo.bmp")
        result = self._reference(asset)
        attachment = self.db.get(ChatImageAttachment, result["id"])
        self.assertEqual(result["content_type"], "image/bmp")
        self.assertEqual(result["filename"], "photo.bmp")
        self.assertEqual(attachment.object_key, asset.object_key)
        cache = {}
        for provider in ("openai", "anthropic"):
            for _ in range(2):
                block = image_content_blocks(self.db, [attachment], provider_type=provider, include_images=True, content_cache=cache)[0]
                if provider == "anthropic":
                    self.assertEqual(block["source"]["media_type"], "image/png")
                    encoded = block["source"]["data"]
                else:
                    self.assertTrue(block["image_url"]["url"].startswith("data:image/png;base64,"))
                    encoded = block["image_url"]["url"].split(",", 1)[1]
                with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (2, 3))
        self.assertEqual(read_attachment_bytes(self.db, asset), output.getvalue())

    def test_failed_database_commit_preserves_original_pixels(self):
        asset = self._asset()
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(HTTPException) as failed:
                self._reference(asset)
        self.assertEqual(failed.exception.status_code, 503)
        self.assertEqual(self.db.query(ChatImageAttachment).count(), 0)
        self.assertEqual(read_attachment_bytes(self.db, asset), PNG)
        self.assertFalse(list(Path(self.directory.name).rglob("chat-images/*.png")))

    def _bind_attachment(self, attachment, *, session=None, superseded=False):
        if session is None:
            session = ChatSession(document_id=self.document.id, title="attachment-test")
            self.db.add(session)
            self.db.flush()
        message = ChatMessage(document_id=self.document.id, session_id=session.id, role=MessageRole.USER,
                              content="replace image", is_superseded=superseded)
        self.db.add(message)
        self.db.flush()
        attachment.message_id = message.id
        self.db.commit()
        return session

    def _run_tools(self, model, edit_session, chat_session, **kwargs):
        store = ToolOutputStore(document_id=self.document.id, session_id=chat_session.id, run_id="attachment-import-test")

        async def go():
            return [event async for event in run_agent_loop(
                model, "attachment-test", edit_session.html, "用@图片1替换正文图片", edit_session.document_map(),
                None, [], session=edit_session, tool_output_store=store, actor_user_id=self.owner.id,
                **kwargs,
             tool_protocol="v1")]

        with patch("app.services.chat_agent.SessionLocal", self.factory), patch("app.services.tool_output_store.SessionLocal", self.factory):
            return asyncio.run(go())

    def _page_attachments(self, count):
        source = self._asset()
        attachments = [self.db.get(ChatImageAttachment, self._reference(source)["id"]) for _ in range(count)]
        chat_session = self._bind_attachment(attachments[0])
        for index, attachment in enumerate(attachments):
            attachment.filename = f"命名图片-{index}.png"
            attachment.message_id = attachments[0].message_id
        ordered = list(reversed(attachments))
        self.db.add(ChatContextEvent(
            document_id=self.document.id, session_id=chat_session.id, message_id=attachments[0].message_id,
            kind=ContextEventKind.USER, ordinal=0,
            payload_json=json.dumps({"content": "比较图片", "image_attachment_ids": [item.id for item in ordered]}),
        ))
        self.db.commit()
        return ordered, chat_session

    def _pages(self, events):
        return [event["data"]["activity"]["details"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "view_chat_images_page" and event["data"]["activity"]["kind"] == "image_view"]

    def test_pages_preserve_order_names_and_release_previous_pixels_for_both_providers(self):
        attachments, chat_session = self._page_attachments(7)
        for provider, image_type in (("openai_compatible", "image_url"), ("anthropic", "image")):
            with self.subTest(provider=provider):
                model = ImagePageToolModel(auto_page=True, page_size=3)
                events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>"), chat_session,
                                         model_is_multimodal=True, provider_type=provider)
                pages = self._pages(events)
                self.assertEqual([error for page in pages for error in page["errors"]], [])
                items = [item for page in pages for item in page["items"]]
                self.assertEqual([item["attachment_id"] for item in items], [item.id for item in attachments])
                self.assertEqual([item["filename"] for item in items], [item.filename for item in attachments])
                self.assertEqual([item["index"] for item in items], list(range(1, 8)))
                self.assertEqual([page["next_cursor"] for page in pages], [3, 6, None])
                self.assertEqual(pages[1]["page_notes"], "已查看上一页")
                for turn, page in zip(model.turns[1:], pages):
                    pixels = [part for message in turn if isinstance(message.content, list) for part in message.content if isinstance(part, dict) and part.get("type") == image_type]
                    self.assertEqual(len(pixels), page["viewed_count"])
                old_page = next(message for message in model.turns[1] if message.additional_kwargs.get("ephemeral_tool_images"))
                released = next(message for message in model.turns[2] if message.id == old_page.id)
                self.assertIsInstance(old_page.content, list)
                self.assertIsInstance(released.content, str)
                self.assertIn("本页画面已释放", released.content)

    def test_metadata_only_pages_have_names_dimensions_and_no_pixels(self):
        attachments, chat_session = self._page_attachments(5)
        model = ImagePageToolModel(auto_page=True, include_image=False, page_size=2)
        events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>"), chat_session, model_is_multimodal=True)
        pages = self._pages(events)
        self.assertEqual(sum(len(page["items"]) for page in pages), len(attachments))
        self.assertTrue(all(not page["image_content_included"] and page["viewed_count"] == 0 for page in pages))
        self.assertTrue(all(not page["include_image_requested"] and "仅读取尺寸" in page["notice"] for page in pages))
        self.assertTrue(all((item["width"], item["height"]) == (1, 1) for page in pages for item in page["items"]))
        self.assertFalse(any(message.additional_kwargs.get("ephemeral_tool_images") for turn in model.turns for message in turn))

    def test_existing_view_tool_reads_a_selected_attachment_url_on_demand(self):
        attachments, chat_session = self._page_attachments(3)
        attachment = attachments[1]
        model = ImagePageToolModel(tool_requests=[{
            "name": "view_article_images",
            "args": {"references": [{"kind": "chat", "url": chat_attachment_url(attachment)}]},
        }])
        events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>"), chat_session,
                                 model_is_multimodal=True)
        result = next(json.loads(message.content) for message in model.turns[-1]
                      if isinstance(message, ToolMessage) and message.name == "view_article_images")
        self.assertEqual(result["items"][0]["attachment_id"], attachment.id)
        self.assertEqual(result["items"][0]["url"], chat_attachment_url(attachment))
        self.assertEqual(result["items"][0]["preview_url"], chat_attachment_url(attachment))
        self.assertTrue(result["include_image_requested"])
        self.assertEqual(result["viewed_count"], 1)
        self.assertFalse(any(message.additional_kwargs.get("ephemeral_tool_images") for message in model.turns[0]))
        self.assertEqual(sum(bool(message.additional_kwargs.get("ephemeral_tool_images")) for message in model.turns[-1]), 1)

    def test_existing_view_tool_rejects_untrusted_urls_and_other_sessions(self):
        attachments, chat_session = self._page_attachments(2)
        other = self.db.get(ChatImageAttachment, self._reference(self._asset())["id"])
        self._bind_attachment(other)
        url = chat_attachment_url(attachments[0])
        references = [
            {"kind": "chat", "url": "https://example.com" + url},
            {"kind": "chat", "url": chat_attachment_url(other)},
            {"kind": "chat", "url": url, "attachment_id": attachments[1].id},
            {"kind": "chat", "url": url.replace(f"/documents/{self.document.id}/", "/documents/999999/")},
        ]
        model = ImagePageToolModel(tool_requests=[{"name": "view_article_images", "args": {"references": references}}])
        with patch("app.services.chat_agent.read_attachment_bytes", side_effect=AssertionError("unauthorized image read")):
            self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>"), chat_session,
                            model_is_multimodal=True)
        result = next(message for message in model.turns[-1]
                      if isinstance(message, ToolMessage) and message.name == "view_article_images")
        self.assertFalse(json.loads(result.content)["ok"])
        self.assertFalse(any(message.additional_kwargs.get("ephemeral_tool_images") for message in model.turns[-1]))

    def test_paged_bmp_is_normalized_without_modifying_original_pixels(self):
        output = io.BytesIO()
        Image.new("RGB", (2, 3), "red").save(output, format="BMP")
        asset = self._asset(output.getvalue(), "product.bmp")
        attachment = self.db.get(ChatImageAttachment, self._reference(asset)["id"])
        chat_session = self._bind_attachment(attachment)
        model = ImagePageToolModel(auto_page=True)
        events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>"), chat_session,
                                 model_is_multimodal=True, provider_type="anthropic")
        self.assertEqual(self._pages(events)[0]["items"][0]["filename"], "product.bmp")
        image_block = next(part for message in model.turns[-1] if isinstance(message.content, list) for part in message.content if isinstance(part, dict) and part.get("type") == "image")
        self.assertEqual(image_block["source"]["media_type"], "image/png")
        with Image.open(io.BytesIO(base64.b64decode(image_block["source"]["data"]))) as image:
            self.assertEqual(image.size, (2, 3))
        self.assertEqual(read_attachment_bytes(self.db, attachment), output.getvalue())

    def test_page_denies_other_session_superseded_and_truncated_messages(self):
        attachments, chat_session = self._page_attachments(2)
        excluded_id = attachments[0].message_id
        chat_session.context_start_message_id = excluded_id
        superseded = self.db.get(ChatImageAttachment, self._reference(self._asset())["id"])
        self._bind_attachment(superseded, session=chat_session, superseded=True)
        other = self.db.get(ChatImageAttachment, self._reference(self._asset())["id"])
        self._bind_attachment(other)
        self.db.commit()
        model = ImagePageToolModel(tool_requests=[{"name": "view_chat_images_page", "args": {"message_id": message_id}} for message_id in (excluded_id, superseded.message_id, other.message_id)])
        with patch("app.services.chat_agent.read_attachment_bytes", side_effect=AssertionError("denied pixels")):
            events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>"), chat_session, model_is_multimodal=True)
        results = [event["data"]["activity"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "view_chat_images_page"]
        self.assertEqual(len(results), 3)
        self.assertTrue(all(result["kind"] == "error" for result in results))

    def test_failed_pixels_advance_cursor_without_skipping_the_next_page(self):
        attachments, chat_session = self._page_attachments(4)
        model = ImagePageToolModel(auto_page=True, page_size=2)
        def read(db, attachment):
            if attachment.id == attachments[0].id:
                raise ValueError("corrupt image")
            return PNG
        with patch("app.services.chat_agent.read_attachment_bytes", side_effect=read):
            events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>"), chat_session, model_is_multimodal=True)
        pages = self._pages(events)
        self.assertEqual([page["next_cursor"] for page in pages], [2, None])
        self.assertEqual(pages[0]["errors"][0]["index"], 1)
        self.assertEqual([item["index"] for page in pages for item in page["items"]], [2, 3, 4])

    def test_page_size_shrinks_to_runtime_context_budget_before_pixel_io(self):
        attachments, chat_session = self._page_attachments(32)
        model = ImagePageToolModel(tool_requests=[{"name": "view_chat_images_page", "args": {"page_size": 32}}])
        with patch("app.services.chat_agent.read_attachment_bytes", return_value=PNG) as read:
            events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>", 10_000), chat_session,
                                     model_is_multimodal=True, run_input_budget_tokens=23_000)
        pages = self._pages(events)
        self.assertEqual(len(pages), 1)
        page = pages[0]
        self.assertLess(page["page_size"], 32)
        self.assertEqual(read.call_count, page["viewed_count"])
        if not page["blocked"]:
            self.assertEqual(page["next_cursor"], page["page_size"])
            self.assertLessEqual(sum(_provider_message_tokens(message, 1.0) for message in model.turns[-1]), 23_000)

    def test_one_hundred_images_continue_across_context_compaction(self):
        attachments, chat_session = self._page_attachments(100)
        model = ImagePageToolModel(auto_page=True)
        summary = {key: "" for key in ("objective", "constraints", "decisions", "completed", "active_work", "blockers", "next_steps", "source_refs")}
        summary.update(objective="比较所有附图", completed="保留已查看页面结论", next_steps="从 next_cursor 继续")
        compactor = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(summary))))
        content = user_message_content(self.db, "比较所有附图", attachments, provider_type="openai_compatible", include_images=True)
        with patch("app.services.chat_agent._effective_run_input_budget", return_value=55_000):
            events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>", 1200), chat_session,
                                     model_is_multimodal=True, run_input_budget_tokens=100_000,
                                     compaction_model=compactor, user_content=content)
        pages = self._pages(events)
        self.assertEqual([error for page in pages for error in page["errors"]], [])
        self.assertEqual([item["attachment_id"] for page in pages for item in page["items"]], [item.id for item in attachments])
        self.assertIsNone(pages[-1]["next_cursor"])
        self.assertFalse(any(page["blocked"] for page in pages))
        self.assertGreater(compactor.ainvoke.await_count, 0)
        self.assertTrue(any(event["event"] == "context_compaction" for event in events))
        self.assertTrue(all(sum(_provider_message_tokens(message) for message in turn) <= 55_000 for turn in model.turns))

    def test_parallel_image_tools_share_the_same_visual_budget(self):
        _attachments, chat_session = self._page_attachments(32)
        model = ImagePageToolModel(tool_requests=[[{"name": "view_chat_images_page", "args": {"cursor": cursor, "page_size": 16}} for cursor in (0, 16)]])
        with patch("app.services.chat_agent.read_attachment_bytes", return_value=PNG) as read:
            events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>", 10_000), chat_session,
                                     model_is_multimodal=True, run_input_budget_tokens=30_000)
        pages = self._pages(events)
        self.assertEqual(len(pages), 2)
        self.assertLess(sum(page["viewed_count"] for page in pages), 32)
        self.assertEqual(read.call_count, sum(page["viewed_count"] for page in pages))
        self.assertLessEqual(sum(_provider_message_tokens(message, 1.0) for message in model.turns[-1]), 30_000)

    def test_zero_page_capacity_reports_unviewed_images_without_pixel_io(self):
        _attachments, chat_session = self._page_attachments(3)
        model = ImagePageToolModel(auto_page=True)
        with patch("app.services.chat_agent.read_attachment_bytes", side_effect=AssertionError("no capacity")):
            events = self._run_tools(model, HtmlEditSession("<section><p>正文</p></section>", 256), chat_session, model_is_multimodal=True)
        page = self._pages(events)[0]
        self.assertTrue(page["blocked"])
        self.assertEqual((page["page_size"], page["viewed_count"], page["next_cursor"]), (0, 0, 0))
        self.assertFalse(page["image_content_included"])

    def test_agent_imports_attachment_and_replaces_image_with_durable_pixels(self):
        original = self._asset()
        result = self._reference(original)
        attachment = self.db.get(ChatImageAttachment, result["id"])
        chat_session = self._bind_attachment(attachment)
        edit_session = HtmlEditSession('<section><h1>Title</h1><figure><img src="old.png"><figcaption>Caption</figcaption></figure><p>Body</p></section>')
        figure = next(item for item in edit_session.search("Caption")["results"] if item["tag"] == "figure")
        read = edit_session.read_blocks([figure["block_id"]])
        block = read["blocks"][0]
        model = AttachmentToolModel(requests=[{"attachment_id": attachment.id}], patch_request={
            "revision": read["revision"], "operations": [{
                "block_id": block["block_id"], "expected_hash": block["expected_hash"], "mode": "replace_inner",
                "html": '<img src="IMPORTED_URL"><figcaption>Caption</figcaption>',
            }],
        })
        with patch("app.services.chat_agent.read_attachment_bytes", side_effect=AssertionError("must reuse library URL")), \
                patch("app.services.document_images.store_tracked_document_image", side_effect=AssertionError("must not upload")):
            events = self._run_tools(model, edit_session, chat_session)
        imported = next(event["data"]["activity"]["details"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "import_chat_image")
        self.assertEqual(events[-1]["event"], "final")
        self.assertIn(imported["url"], edit_session.html)
        self.assertNotIn("old.png", edit_session.html)
        self.assertNotIn("chat-images", edit_session.html)
        self.assertIn("<h1>Title</h1>", edit_session.html)
        self.assertIn("<figcaption>Caption</figcaption>", edit_session.html)
        self.assertIn("<p>Body</p>", edit_session.html)
        asset = self.db.get(ImageLibraryAsset, imported["asset_id"])
        self.assertEqual(asset.id, original.id)
        self.assertEqual(self.db.query(ImageLibraryAsset).count(), 1)
        self.assertEqual(read_attachment_bytes(self.db, asset), PNG)
        delete_attachment_object(self.db, attachment)
        self.assertEqual(read_attachment_bytes(self.db, asset), PNG)

    def test_seventy_gallery_images_have_reusable_article_urls_and_need_no_import_tool(self):
        assets = [self._asset(filename=f"gallery-{index}.png") for index in range(70)]
        references = self._reference_many([asset.id for asset in assets])
        attachments = [self.db.get(ChatImageAttachment, reference["id"]) for reference in references]
        chat_session = self._bind_attachment(attachments[0])
        for attachment in attachments[1:]:
            attachment.message_id = attachments[0].message_id
        self.db.commit()
        edit_session = HtmlEditSession('<section><figure><p>毕业照占位</p></figure><p>Body</p></section>')
        figure = next(item for item in edit_session.search("毕业照占位")["results"] if item["tag"] == "figure")
        read = edit_session.read_blocks([figure["block_id"]])
        model = ImagePageToolModel(tool_requests=[{
            "name": "apply_html_patch", "args": {
                "revision": read["revision"], "operations": [{
                    "block_id": figure["block_id"], "expected_hash": read["blocks"][0]["expected_hash"],
                    "mode": "replace_inner", "html": ''.join(f'<img src="{asset.url}"/>' for asset in assets),
                }],
            },
        }])
        with patch("app.services.chat_images.read_attachment_bytes", side_effect=AssertionError("must not read gallery pixels")), \
                patch("app.services.chat_agent.read_attachment_bytes", side_effect=AssertionError("must not import gallery pixels")), \
                patch("app.services.document_images.store_tracked_document_image", side_effect=AssertionError("must not reupload")):
            content = user_message_content(self.db, "用这70张附图替换占位", attachments,
                                           provider_type="openai_compatible", include_images=True)
            events = self._run_tools(model, edit_session, chat_session, user_content=content, model_is_multimodal=True)
        self.assertIsInstance(content, str)
        self.assertIn("不要再调用 import_chat_image", content)
        for asset in assets:
            self.assertIn(f'article_url="{asset.url}"', content)
            self.assertIn(asset.url, edit_session.html)
        self.assertNotIn("毕业照占位", edit_session.html)
        self.assertIn("<p>Body</p>", edit_session.html)
        self.assertFalse(any(event["event"] == "tool_result" and event["data"]["name"] == "import_chat_image" for event in events))

    def test_agent_materializes_private_pasted_attachment_only_once(self):
        attachment = create_attachment(self.db, document_id=self.document.id, uploader_id=self.owner.id, data=PNG, filename="pasted.png")
        chat_session = self._bind_attachment(attachment)
        model = AttachmentToolModel(requests=[{"attachment_id": attachment.id}, {"attachment_id": attachment.id}])
        events = self._run_tools(model, HtmlEditSession('<section><p>Body</p></section>'), chat_session)
        imports = [event["data"]["activity"]["details"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "import_chat_image"]
        self.assertEqual(len(imports), 2)
        self.assertEqual(imports[0]["asset_id"], imports[1]["asset_id"])
        self.assertEqual(self.db.query(ImageLibraryAsset).count(), 1)
        asset = self.db.get(ImageLibraryAsset, imports[0]["asset_id"])
        self.assertNotEqual(asset.object_key, attachment.object_key)
        delete_attachment_object(self.db, attachment)
        self.assertEqual(read_attachment_bytes(self.db, asset), PNG)

    def test_pasted_pixels_reach_model_and_existing_import_tool_can_replace_article_image(self):
        attachment = create_attachment(self.db, document_id=self.document.id, uploader_id=self.owner.id,
                                       data=PNG, filename="pasted-replacement.png")
        chat_session = self._bind_attachment(attachment)
        self.assertTrue(attachment.is_direct_input)
        edit_session = HtmlEditSession('<section><h1>Title</h1><figure><img src="old.png"/><figcaption>Caption</figcaption></figure><p>Body</p></section>')
        workspace = edit_session.workspace()
        block = next(item for item in workspace.map_payload()["blocks"] if item["tag"] == "figure")
        expected_hash = edit_session.read_blocks([block["block_id"]])["blocks"][0]["expected_hash"]
        content = user_message_content(self.db, "用@图片1替换正文图片", [attachment],
                                       provider_type="openai_compatible", include_images=True)
        model = AttachmentToolModel(requests=[{"attachment_id": attachment.id}], patch_request={
            "revision": workspace.revision,
            "operations": [{"block_id": block["block_id"], "expected_hash": expected_hash,
                            "mode": "replace_inner", "html": '<img src="IMPORTED_URL"/><figcaption>Caption</figcaption>'}],
        })
        events = self._run_tools(model, edit_session, chat_session, user_content=content, model_is_multimodal=True)
        imported = next(event["data"]["activity"]["details"] for event in events
                        if event["event"] == "tool_result" and event["data"]["name"] == "import_chat_image")
        self.assertNotIn("old.png", edit_session.html)
        self.assertIn(imported["url"], edit_session.html)
        self.assertIn("<figcaption>Caption</figcaption>", edit_session.html)
        self.assertIn("<p>Body</p>", edit_session.html)
        self.assertEqual(read_attachment_bytes(self.db, self.db.get(ImageLibraryAsset, imported["asset_id"])), PNG)
        self.assertEqual(content[2]["type"], "image_url")

    def test_import_rejects_other_session_superseded_truncated_and_unbound_images(self):
        source = self._asset()
        attachments = [self.db.get(ChatImageAttachment, self._reference(source)["id"]) for _ in range(4)]
        chat_session = self._bind_attachment(attachments[0])
        chat_session.context_start_message_id = attachments[0].message_id
        self._bind_attachment(attachments[1], session=chat_session, superseded=True)
        self._bind_attachment(attachments[2])
        self.db.commit()
        model = AttachmentToolModel(requests=[{"attachment_id": item.id} for item in attachments])
        edit_session = HtmlEditSession('<section><p>Unchanged</p></section>')
        events = self._run_tools(model, edit_session, chat_session)
        results = [event["data"]["activity"] for event in events if event["event"] == "tool_result" and event["data"]["name"] == "import_chat_image"]
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result["kind"] == "error" for result in results))
        self.assertEqual(self.db.query(ImageLibraryAsset).count(), 1)
        self.assertEqual(edit_session.html, '<section><p>Unchanged</p></section>')
