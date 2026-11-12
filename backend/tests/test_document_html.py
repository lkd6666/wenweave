import unittest

from app.services.document_html import same_document_html


class DocumentHtmlTests(unittest.TestCase):
    def test_browser_serialization_keeps_the_same_document(self):
        cases = [
            ("<p title='标题' class='a'>正文</p>", '<p class="a" title="标题">正文</p>'),
            ('<p>A&nbsp;B &#38; C</p>', '<p>A\u00a0B &amp; C</p>'),
            ('<p>正文<br/><img src="/a.png" /></p>', '<p>正文<br><img src="/a.png"></p>'),
            ('<p>第一行\r\n第二行</p>', '<p>第一行\n第二行</p>'),
            ('<svg viewBox="0 0 10 10"><path d="M0 0"/></svg>',
             '<svg viewBox="0 0 10 10"><path d="M0 0"></path></svg>'),
        ]
        for source, serialized in cases:
            with self.subTest(source=source):
                self.assertTrue(same_document_html(source, serialized))

    def test_content_styles_images_and_significant_whitespace_are_changes(self):
        cases = [
            ('<p>正文</p>', '<p>新正文</p>'),
            ('<p style="color:red">正文</p>', '<p style="color:blue">正文</p>'),
            ('<p class="a">正文</p>', '<p class="b">正文</p>'),
            ('<img src="/a.png">', '<img src="/b.png">'),
            ('<pre>甲  乙\n丙</pre>', '<pre>甲 乙\n丙</pre>'),
            ('<span>甲</span> <span>乙</span>', '<span>甲</span><span>乙</span>'),
            ('<p>A B</p>', '<p>A\u00a0B</p>'),
            ('<svg><path d="M0 0"/></svg>', '<svg><path d="M1 1"/></svg>'),
            ('<svg viewBox="0 0 10 10"></svg>', '<svg viewBox="0 0 20 20"></svg>'),
            ('<style>p{color:red}</style>', '<style>p{color:blue}</style>'),
            ('<!DOCTYPE html><p>正文</p>', '<p>正文</p>'),
        ]
        for source, edited in cases:
            with self.subTest(source=source):
                self.assertFalse(same_document_html(source, edited))
