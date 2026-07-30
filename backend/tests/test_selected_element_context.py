import json
import re
import unittest

from app.schemas.chat import ChatSendRequest
from app.services.chat_agent import HtmlEditSession
from app.services.selected_elements import MAX_SELECTED_ELEMENTS_HTML_CHARS


class SelectedElementContextTests(unittest.TestCase):
    def test_request_strips_inline_data_before_validation_and_caps_total_context(self) -> None:
        inline_image = "data:image/png;base64," + ("A" * 30_000) + "\n" + ("A" * 30_000)
        request = ChatSendRequest.model_validate(
            {
                "message": "调整选中的图片",
                "model_id": 1,
                "session_id": 1,
                "client_request_id": "selected-image-context",
                "selected_elements": [
                    {
                        "selector": f"p:nth-of-type({index + 1})",
                        "tag_name": "p",
                        "html": f'<p><img src="{inline_image}" /></p>',
                        "text": "图片说明",
                    }
                    for index in range(12)
                ],
            }
        )

        html_values = [item.html for item in request.selected_elements]
        self.assertTrue(html_values)
        self.assertTrue(all("data:image" not in value for value in html_values))
        self.assertTrue(all("[inline image data omitted]" in value for value in html_values))
        self.assertLessEqual(sum(len(value) for value in html_values), MAX_SELECTED_ELEMENTS_HTML_CHARS)

    def test_agent_view_redacts_inline_data_and_restores_its_token_for_edits(self) -> None:
        inline_image = "data:image/png;base64," + ("A" * 20_000) + "\n" + ("A" * 20_000)
        session = HtmlEditSession(f'<p><img src="{inline_image}"></p>')

        # 读取路径必须把内联图片换成占位符：模型永远看不到 Base64。
        image_block = next(
            block for block in session.document_map()["blocks"] if block["tag"] == "img"
        )
        read = session.read_blocks([image_block["block_id"]])
        source = read["blocks"][0]["html"]
        self.assertNotIn("data:image", source)
        token = re.search(r"__YIBAN_INLINE_DATA_\d+__", source)
        self.assertIsNotNone(token)
        assert token is not None

        # 模型原样保留占位符改写周边属性，写回时必须还原成原始图片数据。
        summary = session.patch_blocks(
            read["revision"],
            [
                {
                    "block_id": image_block["block_id"],
                    "expected_hash": read["blocks"][0]["expected_hash"],
                    "mode": "replace_outer",
                    "html": f'<img alt="保留图片" src="{token.group(0)}">',
                }
            ],
        )

        self.assertIn(inline_image, session.html)
        self.assertIn('alt="保留图片"', session.html)
        # 回给模型的补丁摘要同样不得泄漏 Base64。
        self.assertNotIn("data:image", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
