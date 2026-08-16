"""HTML5-aware structural validation for Agent-produced HTML."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal

import html5lib
from html5lib.constants import E as HTML5_ERROR_MESSAGES


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
# HTML allows these end tags to be omitted in specific contexts. html5lib checks
# those context rules; the source stack only avoids treating every omission as
# an unconditional error.
OPTIONAL_END_TAGS = frozenset(
    {
        "body",
        "colgroup",
        "dd",
        "dt",
        "head",
        "html",
        "li",
        "optgroup",
        "option",
        "p",
        "rb",
        "rp",
        "rt",
        "rtc",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
    }
)
RAWTEXT_AND_RCDATA_TAGS = (
    "iframe",
    "noembed",
    "noframes",
    "script",
    "style",
    "textarea",
    "title",
    "xmp",
)
MAX_HTML_ERRORS = 12

_FULL_DOCUMENT_START = re.compile(r"(?is)^\s*(?:<!doctype\b|<html\b|<head\b|<body\b)")
_LEADING_COMMENT = re.compile(r"(?is)^\s*<!--.*?-->")
_FRAGMENT_START_TAG = re.compile(r"(?is)^\s*<([a-z][a-z0-9:-]*)\b")
_FRAGMENT_CONTAINERS = {
    "caption": "table",
    "col": "colgroup",
    "colgroup": "table",
    "optgroup": "select",
    "option": "select",
    "tbody": "table",
    "td": "tr",
    "tfoot": "table",
    "th": "tr",
    "thead": "table",
    "tr": "tbody",
}
_NON_STRUCTURAL_HTML5_ERRORS = frozenset(
    {
        "cant-convert-numeric-entity",
        "deprecated-tag",
        "duplicate-attribute",
        "expected-doctype-but-got-chars",
        "expected-doctype-but-got-end-tag",
        "expected-doctype-but-got-eof",
        "expected-doctype-but-got-start-tag",
        "expected-named-entity",
        "expected-numeric-entity",
        "expected-numeric-entity-but-got-eof",
        "illegal-codepoint-for-numeric-entity",
        "illegal-windows-1252-entity",
        "incorrect-cr-newline-entity",
        "named-entity-without-semicolon",
        "numeric-entity-without-semicolon",
        "unknown-doctype",
    }
)
_TOKENIZATION_ERROR_MARKERS = (
    "attribute",
    "comment",
    "doctype",
    "eof-in-tag",
    "expected-dashes",
    "expected-tag-name",
    "invalid-character",
    "unexpected-character",
)


@dataclass(frozen=True)
class HtmlValidationIssue:
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    tag: str = ""
    severity: Literal["error", "warning"] = "error"

    @property
    def display_message(self) -> str:
        if self.line is None:
            return self.message
        if self.column is None:
            return f"第 {self.line} 行：{self.message}"
        return f"第 {self.line} 行第 {self.column} 列：{self.message}"

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "tag": self.tag,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class HtmlValidationReport:
    issues: tuple[HtmlValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(issue.display_message for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(issue.display_message for issue in self.issues if issue.severity == "warning")

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _OpenTag:
    name: str
    line: int
    column: int


class _HtmlStructureParser(HTMLParser):
    # HTMLParser only handles script/style as text by default. Extending its
    # raw-text list prevents tags shown inside textarea/title from entering the
    # source stack, matching HTML5 tokenization for structural purposes.
    CDATA_CONTENT_ELEMENTS = RAWTEXT_AND_RCDATA_TAGS

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[_OpenTag] = []
        self.issues: list[HtmlValidationIssue] = []

    def _position(self) -> tuple[int, int]:
        line, zero_based_column = self.getpos()
        return line, zero_based_column + 1

    def _add_issue(
        self,
        code: str,
        message: str,
        *,
        tag: str = "",
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        if len(self.issues) >= MAX_HTML_ERRORS:
            return
        issue = HtmlValidationIssue(code=code, message=message, line=line, column=column, tag=tag)
        if issue not in self.issues:
            self.issues.append(issue)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name not in VOID_TAGS:
            line, column = self._position()
            self.stack.append(_OpenTag(name=name, line=line, column=column))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # html5lib determines whether the self-closing syntax is legal in the
        # current HTML/SVG/MathML namespace. Do not duplicate that logic here.
        return

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        line, column = self._position()
        if name in VOID_TAGS:
            self._add_issue(
                "void_end_tag",
                f"void 标签 <{name}> 不能使用结束标签 </{name}>；请删除结束标签。",
                tag=name,
                line=line,
                column=column,
            )
            return

        match_index = next(
            (index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index].name == name),
            None,
        )
        if match_index is None:
            self._add_issue(
                "unmatched_end_tag",
                f"结束标签 </{name}> 没有可匹配的 <{name}>；请删除它或补上起始标签。",
                tag=name,
                line=line,
                column=column,
            )
            return

        missing = [item for item in self.stack[match_index + 1 :] if item.name not in OPTIONAL_END_TAGS]
        if missing:
            details = "、".join(
                f"<{item.name}>（始于第 {item.line} 行第 {item.column} 列）" for item in reversed(missing)
            )
            fixes = "".join(f"</{item.name}>" for item in reversed(missing))
            self._add_issue(
                "missing_end_tag_before_close",
                f"结束标签 </{name}> 闭合过早；其内部的 {details} 尚未闭合。请在 </{name}> 前补上 {fixes}。",
                tag=name,
                line=line,
                column=column,
            )
        del self.stack[match_index:]


def _looks_like_full_document(html: str) -> bool:
    candidate = html
    while match := _LEADING_COMMENT.match(candidate):
        candidate = candidate[match.end() :]
    return bool(_FULL_DOCUMENT_START.match(candidate))


def _fragment_container(html: str) -> str:
    candidate = html
    while match := _LEADING_COMMENT.match(candidate):
        candidate = candidate[match.end() :]
    start = _FRAGMENT_START_TAG.match(candidate)
    return _FRAGMENT_CONTAINERS.get(start.group(1).lower(), "div") if start else "div"


def _tag_name(data: dict[str, Any]) -> str:
    return str(
        data.get("name")
        or data.get("startName")
        or data.get("gotName")
        or data.get("originalName")
        or ""
    ).lower()


def _html5_issue(code: str, data: dict[str, Any], line: int, column: int) -> HtmlValidationIssue:
    name = _tag_name(data)
    if code == "non-void-element-with-trailing-solidus":
        message = f"非 void 标签 <{name}/> 不能自闭合；浏览器会把它当作 <{name}>。请改为 <{name}></{name}>。"
    elif code.startswith("eof-in-comment"):
        message = "HTML 注释未闭合；请在文档结束前补上 -->。"
    elif code in {
        "eof-in-attribute-name",
        "eof-in-attribute-value-double-quote",
        "eof-in-attribute-value-no-quotes",
        "eof-in-attribute-value-single-quote",
        "expected-attribute-name-but-got-eof",
        "expected-attribute-value-but-got-eof",
    }:
        message = "标签属性在文档末尾被截断；请检查属性名、等号以及成对的引号。"
    elif code in {
        "eof-in-tag-name",
        "expected-end-of-tag-name-but-got-eof",
        "unexpected-EOF-after-solidus-in-tag",
    }:
        message = "标签在文档末尾被截断；请补全标签名和右尖括号 >。"
    elif code == "expected-closing-tag-but-got-eof":
        message = "文档结束时仍有未闭合元素；请根据同一报告中的起始标签位置补全结束标签。"
    elif code in {"end-tag-too-early", "end-tag-too-early-ignored"}:
        message = f"结束标签 </{name}> 出现过早；它前面仍有需要先闭合的子元素。"
    elif code in {"end-tag-too-early-named", "expected-one-end-tag-but-got-another"}:
        got = str(data.get("gotName") or name).lower()
        expected = str(data.get("expectedName") or "").lower()
        message = f"结束标签顺序错误：遇到 </{got}> 时应先闭合 </{expected}>。"
        name = got
    elif code in {"unexpected-end-tag", "end-tag-after-implied-root", "unexpected-end-tag-after-body"}:
        message = f"结束标签 </{name}> 在浏览器解析到这里时已没有对应的起始标签；请检查前面的隐式闭合或删除该标签。"
    elif code == "unexpected-end-tag-treated-as":
        original = str(data.get("originalName") or name).lower()
        message = f"结束标签 </{original}> 会被浏览器改写为其他节点；请使用合法的标签配对。"
        name = original
    elif code == "unexpected-start-tag-implies-end-tag":
        start = str(data.get("startName") or name).lower()
        ended = str(data.get("endName") or "").lower()
        message = f"起始标签 <{start}> 会让浏览器提前闭合外层 <{ended}>；请勿嵌套这类元素。"
        name = start
    elif code.startswith("adoption-agency"):
        message = f"格式化标签 <{name}> 的嵌套顺序无效，浏览器会重排节点；请按打开顺序的反序闭合标签。"
    elif "table-voodoo" in code:
        message = f"标签 <{name}> 不能直接出现在当前 table 层级；浏览器会把它移出表格。请放入合法的 thead/tbody/tr/td 结构。"
    elif code in {"unexpected-cell-in-table-body", "unexpected-cell-end-tag"}:
        message = f"表格单元格 <{name}> 所在层级无效；请确保结构为 table > tbody/thead/tfoot > tr > td/th。"
    elif code.startswith("unexpected-implied-end-tag-in-table"):
        message = f"表格中的 <{name}> 会被浏览器隐式闭合；请显式补全并检查 table/tr/td 的嵌套顺序。"
    elif code in {
        "unexpected-end-tag-in-select",
        "unexpected-input-in-select",
        "unexpected-select-in-select",
        "unexpected-start-tag-in-select",
    }:
        message = f"标签 <{name}> 不允许出现在当前 select 层级；请只保留合法的 option/optgroup 结构。"
    elif code == "attributes-in-end-tag":
        message = f"结束标签 </{name}> 不能包含属性；请删除结束标签中的属性。"
    elif code == "self-closing-flag-on-end-tag":
        message = f"结束标签 </{name}> 不能使用自闭合斜杠。"
    elif "comment" in code:
        message = "HTML 注释语法无效；注释应使用 <!-- 内容 -->，且内容中不要再次出现 <!-- 或 --。"
    elif code in {
        "expected-dashes-or-doctype",
        "expected-tag-name",
        "expected-tag-name-but-got-question-mark",
        "expected-tag-name-but-got-right-bracket",
    }:
        message = "检测到不完整或非法的 HTML 声明/标签起始符；请检查附近的 <、> 和标签名。"
    else:
        template = HTML5_ERROR_MESSAGES.get(code, code)
        try:
            detail = template % data
        except (KeyError, TypeError, ValueError):
            detail = template
        message = f"HTML5 解析错误（{code}）：{detail}"
    return HtmlValidationIssue(code=f"html5.{code}", message=message, line=line, column=column, tag=name)


def _append_html5_issues(html: str, issues: list[HtmlValidationIssue]) -> None:
    try:
        parser = html5lib.HTMLParser(strict=False, namespaceHTMLElements=False)
        if _looks_like_full_document(html):
            parser.parse(html)
        else:
            parser.parseFragment(html, container=_fragment_container(html))
    except Exception as exc:  # pragma: no cover - protects writes if the dependency fails unexpectedly.
        issues.append(HtmlValidationIssue(code="html5_parser_failure", message=f"HTML5 解析失败：{exc}"))
        return

    source_codes = {issue.code for issue in issues}
    source_unmatched_tags = {issue.tag for issue in issues if issue.code == "unmatched_end_tag"}
    for (line, column), code, raw_data in parser.errors:
        if code in _NON_STRUCTURAL_HTML5_ERRORS:
            continue
        data = raw_data if isinstance(raw_data, dict) else {}
        if code == "expected-closing-tag-but-got-eof" and "missing_end_tag_at_eof" in source_codes:
            continue
        if code in {"end-tag-too-early", "end-tag-too-early-ignored"} and "missing_end_tag_before_close" in source_codes:
            continue
        if code == "unexpected-end-tag-treated-as" and "void_end_tag" in source_codes:
            continue
        name = _tag_name(data)
        if code == "unexpected-end-tag" and name in OPTIONAL_END_TAGS and name not in source_unmatched_tags:
            issue = HtmlValidationIssue(
                code=f"html5.{code}",
                message=(
                    f"结束标签 </{name}> 对应的源码起始标签已被 HTML5 规则提前隐式闭合；"
                    "浏览器会忽略这个结束标签，正文仍可安全加载。"
                ),
                line=int(line),
                column=int(column),
                tag=name,
                severity="warning",
            )
        else:
            issue = _html5_issue(code, data, int(line), int(column))
        if "table-voodoo" in code and any(
            existing.message == issue.message and existing.tag == issue.tag for existing in issues
        ):
            continue
        if issue not in issues:
            issues.append(issue)
            issues.sort(key=_issue_priority)
            del issues[MAX_HTML_ERRORS:]


def _issue_priority(issue: HtmlValidationIssue) -> int:
    if issue.severity == "warning":
        return 3
    if issue.code.startswith("html5.") and any(marker in issue.code for marker in _TOKENIZATION_ERROR_MARKERS):
        return 0
    if not issue.code.startswith("html5."):
        return 1
    return 2


def validate_html_structure(html: str) -> HtmlValidationReport:
    """Return source-level and HTML5 tree-construction errors without rewriting HTML."""
    if not html.strip():
        return HtmlValidationReport()

    parser = _HtmlStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser is tolerant, but preserve unexpected failures.
        parser._add_issue("source_parser_failure", f"源码标签扫描失败：{exc}")

    for item in reversed(parser.stack):
        if len(parser.issues) >= MAX_HTML_ERRORS or item.name in OPTIONAL_END_TAGS:
            continue
        parser._add_issue(
            "missing_end_tag_at_eof",
            f"<{item.name}>（始于第 {item.line} 行第 {item.column} 列）在文档结束时仍未闭合；请补上 </{item.name}>。",
            tag=item.name,
            line=item.line,
            column=item.column,
        )

    _append_html5_issues(html, parser.issues)
    ordered = sorted(parser.issues, key=_issue_priority)
    return HtmlValidationReport(issues=tuple(ordered[:MAX_HTML_ERRORS]))
