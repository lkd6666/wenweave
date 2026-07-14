"""Lightweight structural validation for HTML fragments produced by the Agent."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser


VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
OPTIONAL_END_TAGS = frozenset(
    {"colgroup", "dd", "dt", "head", "html", "li", "optgroup", "option", "p", "tbody", "td", "tfoot", "th", "thead", "tr"}
)
AUTO_CLOSE_ON_START = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "option": {"option"},
    "optgroup": {"optgroup"},
    "p": {"p"},
    "tr": {"tr"},
    "td": {"td", "th"},
    "th": {"td", "th"},
}
MAX_HTML_ERRORS = 12


@dataclass(frozen=True)
class HtmlValidationReport:
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {"valid": self.valid, "errors": list(self.errors)}


class _HtmlStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def _add_error(self, message: str) -> None:
        if len(self.errors) < MAX_HTML_ERRORS and message not in self.errors:
            self.errors.append(message)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        auto_close = AUTO_CLOSE_ON_START.get(name, set())
        if self.stack and self.stack[-1] in auto_close:
            self.stack.pop()
        if name not in VOID_TAGS:
            self.stack.append(name)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in VOID_TAGS:
            self._add_error(f"void 标签 <{name}> 不应使用结束标签 </{name}>")
            return
        try:
            index = len(self.stack) - 1 - self.stack[::-1].index(name)
        except ValueError:
            self._add_error(f"结束标签 </{name}> 没有对应的起始标签")
            return

        skipped = self.stack[index + 1 :]
        missing = [item for item in skipped if item not in OPTIONAL_END_TAGS]
        if missing:
            missing_tags = "、".join(f"</{item}>" for item in reversed(missing))
            self._add_error(f"在 </{name}> 前缺少结束标签：{missing_tags}")
        del self.stack[index:]


def validate_html_structure(html: str) -> HtmlValidationReport:
    """Return actionable structural errors without normalizing or changing the source."""
    if not html.strip():
        return HtmlValidationReport(errors=())

    parser = _HtmlStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser is tolerant, but preserve any unexpected parser failure.
        parser._add_error(f"HTML 解析失败：{exc}")

    if html.count("<!--") != html.count("-->"):
        parser._add_error("HTML 注释未闭合（<!-- 与 --> 数量不一致）")

    # Script/style content can legally contain '<', so ignore raw-text blocks before checking a trailing tag.
    markup_only = re.sub(r"<(script|style)\b[^>]*>[\s\S]*?</\1\s*>", "", html, flags=re.IGNORECASE)
    last_open = markup_only.rfind("<")
    if last_open > markup_only.rfind(">"):
        snippet = re.sub(r"\s+", " ", markup_only[last_open : last_open + 80]).strip()
        parser._add_error(f"存在未闭合的标签或声明：{snippet}")

    unclosed = [tag for tag in parser.stack if tag not in OPTIONAL_END_TAGS]
    if unclosed:
        missing_tags = "、".join(f"</{tag}>" for tag in reversed(unclosed))
        parser._add_error(f"文档结束时缺少结束标签：{missing_tags}")

    return HtmlValidationReport(errors=tuple(parser.errors))
