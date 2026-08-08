import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import app.models  # noqa: F401 - register the full metadata graph for SQLite.
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.chat import _attached_template_payload
from app.api.routes.template_library import delete_category, delete_template, list_templates
from app.db.base import Base
from app.models.template_library import TemplateCategory, TemplateImageAsset, TemplateLibraryItem, TemplateSourceType
from app.services.local_uploads import ImageInfo
from app.services.template_library import (
    TemplateLibraryError,
    _fetch_remote_image,
    _html_fragment,
    _normalise_html,
    localize_template_html,
    remove_unreferenced_assets,
)


class TemplateLibraryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _template(self, name: str = "测试组件", category_id: int | None = None) -> TemplateLibraryItem:
        template = TemplateLibraryItem(
            name=name,
            category_id=category_id,
            html="<p>原始内容</p>",
            source_type=TemplateSourceType.SOURCE,
        )
        self.db.add(template)
        self.db.flush()
        return template

    def test_sanitizes_scripts_events_dangerous_urls_and_interactive_tags(self) -> None:
        html = _html_fragment(_normalise_html("""
          <section id="unsafe" class="card" onclick="alert(1)">
            <style>body { display:none }</style><script>steal()</script>
            <a href="javascript:alert(1)" target="_blank">链接</a>
            <img src="file:///secret.png" onerror="steal()" />
            <button>不要保留</button><p style="color:#1677ff">安全正文</p>
            <p style="background:url(javascript:alert(1))">危险样式</p>
          </section>
        """))

        self.assertIn("安全正文", html)
        self.assertIn('style="color:#1677ff"', html)
        self.assertNotIn("script", html)
        self.assertNotIn("button", html)
        self.assertNotIn("onclick", html)
        self.assertNotIn("onerror", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("file:", html)
        self.assertNotIn("background:url(javascript", html)
        self.assertNotIn('id="unsafe"', html)
        self.assertNotIn('class="card"', html)

    def test_private_remote_address_is_rejected_before_http_request(self) -> None:
        async def run() -> None:
            async with httpx.AsyncClient() as client:
                with self.assertRaisesRegex(TemplateLibraryError, "本机或内网"):
                    await _fetch_remote_image(client, "https://127.0.0.1/secret.png")

        asyncio.run(run())

    def test_failed_image_transfer_rejects_component_without_mutating_it(self) -> None:
        template = self._template()

        async def rejected(*_args, **_kwargs):
            raise Exception("图片无法访问")

        with patch("app.services.template_library.fetch_public_image", new=rejected):
            with self.assertRaisesRegex(TemplateLibraryError, "图片无法访问"):
                asyncio.run(localize_template_html(
                    self.db,
                    template,
                    '<section><img src="https://images.example.test/hero.png" /><p>正文</p></section>',
                ))

        self.assertEqual(template.html, "<p>原始内容</p>")
        self.assertEqual(self.db.query(TemplateImageAsset).count(), 0)

    def test_localizes_src_srcset_and_background_images_once_per_source(self) -> None:
        template = self._template()
        image = ImageInfo("image/png", "png")
        stored: list[TemplateImageAsset] = []

        def store_asset(_db, template_id, _data, _image, source):
            asset = TemplateImageAsset(
                id=f"00000000-0000-0000-0000-{len(stored) + 1:012d}",
                template_id=template_id,
                original_url=source,
                object_key=f"local/template-library/{len(stored)}.png",
                storage_mode="local",
                content_type="image/png",
                size=1,
            )
            stored.append(asset)
            self.db.add(asset)
            return asset

        fetch = AsyncMock(return_value=(b"image", image))
        with (
            patch("app.services.template_library.fetch_public_image", new=fetch),
            patch("app.services.template_library._store_asset", side_effect=store_asset),
        ):
            result = asyncio.run(localize_template_html(
                self.db,
                template,
                '<section style="background-image:url(https://images.example.test/hero.png)">'
                '<img src="https://images.example.test/hero.png" '
                'srcset="https://images.example.test/hero.png 1x, https://images.example.test/card.png 2x" />'
                '</section>',
            ))

        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(result.localized_count, 2)
        self.assertEqual(len(stored), 2)
        self.assertNotIn("images.example.test", result.html)
        self.assertIn("srcset=", result.html)
        self.assertIn("background-image:url(/api/template-library/assets/", result.html)

    def test_category_delete_moves_templates_to_uncategorized_for_every_user(self) -> None:
        category = TemplateCategory(name="活动", sort_order=1)
        self.db.add(category)
        self.db.flush()
        template = self._template(category_id=category.id)
        self.db.commit()

        delete_category(category.id, current_user=SimpleNamespace(id=200, role="user"), db=self.db)

        self.db.refresh(template)
        self.assertIsNone(template.category_id)
        self.assertIsNone(self.db.get(TemplateCategory, category.id))

    def test_template_delete_cleans_transferred_assets(self) -> None:
        template = self._template()
        asset = TemplateImageAsset(
            id="d4c6ec15-7422-45da-8c45-0fc5600f3a80",
            template_id=template.id,
            original_url="https://images.example.test/hero.png",
            object_key="local/template-library/hero.png",
            storage_mode="local",
            content_type="image/png",
            size=12,
        )
        self.db.add(asset)
        self.db.commit()

        with patch("app.api.routes.template_library.delete_asset_object") as delete_object:
            delete_template(template.id, current_user=SimpleNamespace(id=201, role="user"), db=self.db)

        delete_object.assert_called_once()
        self.assertIsNone(self.db.get(TemplateLibraryItem, template.id))
        self.assertIsNone(self.db.get(TemplateImageAsset, asset.id))

    def test_removes_assets_no_longer_referenced_by_updated_html(self) -> None:
        template = self._template()
        asset = TemplateImageAsset(
            id="fcecdc37-9839-4edc-a832-e0144be62804",
            template_id=template.id,
            original_url="https://images.example.test/hero.png",
            object_key="local/template-library/old.png",
            storage_mode="local",
            content_type="image/png",
            size=12,
        )
        self.db.add(asset)
        self.db.flush()

        with patch("app.services.template_library.delete_asset_object") as delete_object:
            remove_unreferenced_assets(self.db, template, "<p>新内容</p>")

        delete_object.assert_called_once_with(self.db, asset)
        self.db.flush()
        self.assertIsNone(self.db.get(TemplateImageAsset, asset.id))

    def test_attached_template_reader_can_only_resolve_selected_ids(self) -> None:
        first = self._template("已附模板")
        second = self._template("未附模板")
        self.db.commit()

        attached = _attached_template_payload(self.db, [first.id])
        self.assertEqual(attached, [{"id": first.id, "name": "已附模板", "html": "<p>原始内容</p>"}])
        self.assertNotIn(second.id, [item["id"] for item in attached])
        with self.assertRaises(HTTPException):
            _attached_template_payload(self.db, [999999])

    def test_template_list_can_sort_by_name(self) -> None:
        self._template("组件 Z")
        self._template("组件 A")
        self.db.commit()

        items = list_templates(category_id=None, q="", sort="name", current_user=SimpleNamespace(id=202, role="user"), db=self.db)

        self.assertEqual([item["name"] for item in items], ["组件 A", "组件 Z"])


if __name__ == "__main__":
    unittest.main()
