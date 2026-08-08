import asyncio
import unittest
from unittest.mock import AsyncMock

from app.services.image_localization import StoredImage, localize_html_images
from app.services.local_uploads import ImageInfo


class ImageLocalizationTests(unittest.TestCase):
    def test_rewrites_data_src_srcset_and_css_and_deduplicates_sources(self) -> None:
        image = ImageInfo("image/png", "png")
        data_url = "data:image/png;base64,AAAA"
        sources = [data_url, "https://images.example.test/hero.png"]
        load_image = AsyncMock(side_effect=[(b"data", image), (b"hero", image)])
        stored: list[StoredImage] = []

        def store_image(_data, _image, source):
            persisted = StoredImage(url=f"/images/{len(stored)}.png", handle=source)
            stored.append(persisted)
            return persisted

        result = asyncio.run(localize_html_images(
            f'<section style="background:url({data_url})"><img src="https://images.example.test/hero.png" '
            f'srcset="{data_url} 1x, https://images.example.test/hero.png 2x"></section>',
            load_image=load_image,
            store_image=store_image,
            cleanup_image=lambda _stored: None,
            is_local_source=lambda _source: False,
            max_images=10,
            max_total_bytes=1024,
        ))

        self.assertEqual(load_image.await_count, 2)
        self.assertEqual(result.localized_count, 2)
        self.assertNotIn("images.example.test", result.html)
        self.assertNotIn(data_url, result.html)
        self.assertIn("srcset=", result.html)
        self.assertIn("background:url(/images/0.png)", result.html)
        self.assertEqual([call.args[0] for call in load_image.await_args_list], sources)
