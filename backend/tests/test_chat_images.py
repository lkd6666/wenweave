import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.chat_images import attachment_text_suffix, duplicate_attachment, image_content_blocks, user_message_content


class ChatImageContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.attachment = SimpleNamespace(content_type="image/png")

    def test_openai_compatible_uses_data_url_image_block(self) -> None:
        with patch("app.services.chat_images.read_attachment_bytes", return_value=b"image-bytes"):
            blocks = image_content_blocks(
                None,
                [self.attachment],
                provider_type="openai_compatible",
                include_images=True,
            )

        self.assertEqual(blocks[0]["type"], "image_url")
        self.assertEqual(blocks[0]["image_url"]["url"], "data:image/png;base64,aW1hZ2UtYnl0ZXM=")

    def test_anthropic_uses_base64_image_block(self) -> None:
        with patch("app.services.chat_images.read_attachment_bytes", return_value=b"image-bytes"):
            blocks = image_content_blocks(
                None,
                [self.attachment],
                provider_type="anthropic",
                include_images=True,
            )

        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["source"], {
            "type": "base64",
            "media_type": "image/png",
            "data": "aW1hZ2UtYnl0ZXM=",
        })

    def test_text_only_fallback_keeps_attachment_notice(self) -> None:
        self.assertEqual(attachment_text_suffix([self.attachment], False), "\n\n[该消息包含 1 张图片；当前模型不支持读取图片。]")
        content = user_message_content(
            None,
            "请处理",
            [self.attachment],
            provider_type="openai_compatible",
            include_images=False,
        )
        self.assertIsInstance(content, str)
        self.assertIn("当前模型不支持读取图片", content)

    def test_duplicate_sent_image_creates_a_new_draft_for_the_requesting_user(self) -> None:
        source = SimpleNamespace(document_id=42, filename="history.png")
        copied = SimpleNamespace(id="new-draft")
        with (
            patch("app.services.chat_images.read_attachment_bytes", return_value=b"image-bytes") as read_bytes,
            patch("app.services.chat_images.create_attachment", return_value=copied) as create,
        ):
            result = duplicate_attachment(None, source=source, uploader_id=99)

        self.assertIs(result, copied)
        read_bytes.assert_called_once_with(None, source)
        create.assert_called_once_with(
            None,
            document_id=42,
            uploader_id=99,
            data=b"image-bytes",
            filename="history.png",
        )


if __name__ == "__main__":
    unittest.main()
