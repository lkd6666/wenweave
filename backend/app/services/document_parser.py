"""PDF / Word 文档解析，按正文内容顺序输出文本与图片。"""
from __future__ import annotations

import io
from typing import Any, Callable, List

# (图片二进制, 文件名, content-type) -> 上传后的外链 URL
ImageUploader = Callable[[bytes, str, str], str]

_VML_IMAGE_DATA_TAG = "{urn:schemas-microsoft-com:vml}imagedata"
_RELATIONSHIP_ID_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _image_tag(url: str) -> str:
    return f'<img src="{url}" alt="图片" style="max-width:100%;height:auto;" />'


def _image_content_type(ext: str) -> str:
    normalized = ext.lower().lstrip(".")
    if normalized in {"jpg", "jpeg"}:
        return "image/jpeg"
    if normalized == "svg":
        return "image/svg+xml"
    return f"image/{normalized or 'png'}"


def _append_pdf_text_block(html_parts: List[str], block: dict) -> None:
    for line in block.get("lines", []):
        text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
        if text:
            html_parts.append(f"<p>{_escape_html(text)}</p>")


def parse_pdf(file_bytes: bytes, upload_image: ImageUploader) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    html_parts: List[str] = []
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            # PDF 没有 Word 那样的语义化流。dict 内容块按页面坐标排序后，是文本与可见
            # 图片最接近原始阅读顺序的表示，比先取全文、再取全部图片更符合实际版面。
            page_content = page.get_text("dict", sort=True)
            image_index = 0
            for block in page_content.get("blocks", []):
                if block.get("type") == 0:
                    _append_pdf_text_block(html_parts, block)
                    continue
                if block.get("type") != 1:
                    continue
                image_bytes = block.get("image")
                if not image_bytes:
                    continue
                image_index += 1
                ext = str(block.get("ext") or "png")
                filename = f"pdf_p{page_index + 1}_{image_index}.{ext}"
                url = upload_image(image_bytes, filename, _image_content_type(ext))
                html_parts.append(f"<p>{_image_tag(url)}</p>")
    finally:
        doc.close()

    return "\n".join(html_parts) or "<p>（PDF 未提取到文本内容）</p>"


def _docx_image_tags(node: Any, document: Any, upload_image: ImageUploader) -> list[str]:
    """解析一个 drawing / pict 节点中的图片关系，并按节点内出现顺序上传。"""
    from docx.oxml.ns import qn

    relationship_ids: list[str] = []
    for child in node.iter():
        if child.tag == qn("a:blip"):
            relationship_id = child.get(qn("r:embed"))
        elif child.tag == _VML_IMAGE_DATA_TAG:
            relationship_id = child.get(_RELATIONSHIP_ID_ATTR)
        else:
            continue
        if relationship_id:
            relationship_ids.append(relationship_id)

    tags: list[str] = []
    for relationship_id in relationship_ids:
        image_part = document.part.related_parts.get(relationship_id)
        if not image_part:
            continue
        part_name = str(image_part.partname)
        filename = part_name.rsplit("/", 1)[-1] or "image.png"
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "png"
        url = upload_image(image_part.blob, filename, image_part.content_type or _image_content_type(ext))
        tags.append(_image_tag(url))
    return tags


def _render_docx_paragraph(paragraph: Any, document: Any, upload_image: ImageUploader) -> str:
    """保留段落内文字、换行和图片的 XML 顺序。"""
    from docx.oxml.ns import qn

    contents: list[str] = []
    for node in paragraph._p.iter():
        if node.tag == qn("w:t"):
            contents.append(_escape_html(node.text or ""))
        elif node.tag in {qn("w:br"), qn("w:cr")}:
            contents.append("<br />")
        elif node.tag in {qn("w:drawing"), qn("w:pict")}:
            contents.extend(_docx_image_tags(node, document, upload_image))

    content = "".join(contents).strip()
    if not content:
        return ""
    style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
    if "heading" in style_name:
        return f"<h3>{content}</h3>"
    return f"<p>{content}</p>"


def _iter_docx_body_paragraphs(document: Any):
    """按 body 顺序返回段落，也处理表格单元格中的段落。"""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document._body)
        elif child.tag == qn("w:tbl"):
            for paragraph_element in child.iter(qn("w:p")):
                yield Paragraph(paragraph_element, document._body)


def parse_docx(file_bytes: bytes, upload_image: ImageUploader) -> str:
    from docx import Document as DocxDocument

    buffer = io.BytesIO(file_bytes)
    document = DocxDocument(buffer)

    html_parts: List[str] = []
    for paragraph in _iter_docx_body_paragraphs(document):
        rendered = _render_docx_paragraph(paragraph, document, upload_image)
        if rendered:
            html_parts.append(rendered)

    return "\n".join(html_parts) or "<p>（Word 未提取到文本内容）</p>"
