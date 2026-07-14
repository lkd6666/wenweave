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

        rendered, _ = session.view()
        self.assertNotIn("data:image", rendered)
        token = re.search(r"__YIBAN_INLINE_DATA_\d+__", rendered)
        self.assertIsNotNone(token)
        assert token is not None

        _, summary = session.str_replace(
            f'<img src="{token.group(0)}">',
            f'<img alt="保留图片" src="{token.group(0)}">',
        )
        self.assertIn(inline_image, session.html)
        self.assertIn('alt="保留图片"', session.html)
        self.assertNotIn("data:image", summary["diff_preview"])


if __name__ == "__main__":
    unittest.main()
