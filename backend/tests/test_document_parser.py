import io
import unittest

import fitz
from docx import Document

from app.services.document_parser import parse_docx, parse_pdf


PNG_BYTES = fitz.Pixmap(fitz.csRGB, (0, 0, 1, 1), 0).tobytes("png")


class DocumentParserOrderTests(unittest.TestCase):
    def _uploader(self):
        uploaded: list[str] = []

        def upload_image(_data: bytes, filename: str, _content_type: str) -> str:
            url = f"https://images.test/{len(uploaded) + 1}-{filename}"
            uploaded.append(url)
            return url

        return uploaded, upload_image

    def test_docx_keeps_inline_image_between_text(self):
        document = Document()
        image_paragraph = document.add_paragraph()
        image_paragraph.add_run("Before image")
        image_paragraph.add_run().add_picture(io.BytesIO(PNG_BYTES))
        image_paragraph.add_run("After image")
        payload = io.BytesIO()
        document.save(payload)

        uploaded, uploader = self._uploader()
        html = parse_docx(payload.getvalue(), uploader)

        self.assertEqual(len(uploaded), 1)
        self.assertLess(html.index("Before image"), html.index(uploaded[0]))
        self.assertLess(html.index(uploaded[0]), html.index("After image"))

    def test_pdf_keeps_image_between_text_blocks(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Before image")
        page.insert_image(fitz.Rect(72, 96, 172, 196), stream=PNG_BYTES)
        page.insert_text((72, 228), "After image")
        payload = document.tobytes()
        document.close()

        uploaded, uploader = self._uploader()
        html = parse_pdf(payload, uploader)

        self.assertEqual(len(uploaded), 1)
        self.assertLess(html.index("Before image"), html.index(uploaded[0]))
        self.assertLess(html.index(uploaded[0]), html.index("After image"))


if __name__ == "__main__":
    unittest.main()
