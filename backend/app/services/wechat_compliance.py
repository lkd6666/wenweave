"""
微信公众号 HTML/SVG 排版规范自动检查工具 —— Python 移植版

与仓库根目录下的 `wechat_format_rules_source.js` 保持规则同步，作为 Web 应用后端的
实时合规检测引擎使用（供 AI 多轮编辑 Agent 的自检自修循环、以及 `/api/compliance/check`
接口共同调用）。规则的可信度分类（已证实 / 经验建议 / 风险提示）与详细逆向依据，
请参考 `wechat_format_rules_source.js` 顶部注释与仓库根目录 `rule.prompt.md`，
本文件的函数级注释只做简要说明，不重复贴述完整调查过程。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Pattern, Union

# ==========================================
# 1.【已证实】class 白名单 / 正则 / 黑名单
# 来源：@tencent/mp-common-appmsg-content -> editor/plugin/filter.js
# ==========================================
CLASS_WHITE_LIST: List[str] = [
    "rich_pages", "blockquote_info", "blockquote_biz", "blockquote_other",
    "blockquote_article", "h5_image_link", "img_loading", "list-paddingleft-1",
    "list-paddingleft-2", "list-paddingleft-3", "selectTdClass", "noBorderTable",
    "ue-table-interlace-color-single", "ue-table-interlace-color-double", "__bg_gif",
    "normal_text_link", "mp_article_text_link", "album", "weapp_text_link", "weapp_image_link",
    "product_image_link", "qqmusic_area", "tc", "tips_global", "unsupport_tips",
    "qqmusic_wrp", "appmsg_card_context", "appmsg_card_active", "qqmusic_bd",
    "play_area", "icon_qqmusic_switch", "pic_qqmusic_default", "qqmusic_thumb",
    "access_area", "qqmusic_songname", "qqmusic_singername", "qqmusic_source",
    "share_audio_context", "flex_context", "pages_reset", "share_audio_switch",
    "icon_share_audio_switch", "share_audio_info", "flex_bd", "share_audio_title",
    "share_audio_tips", "share_audio_progress_wrp", "share_audio_progress",
    "share_audio_progress_inner", "share_audio_progress_buffer",
    "share_audio_progress_loading", "share_audio_progress_loading_inner",
    "share_audio_progress_handle", "share_audio_desc", "share_audio_length_current",
    "share_audio_length_total", "video_iframe", "vote_iframe", "res_iframe",
    "card_iframe", "weapp_display_element", "weapp_card", "app_context",
    "weapp_card_bd", "weapp_card_profile", "radius_avatar", "weapp_card_avatar",
    "weapp_card_nickname", "weapp_card_info", "weapp_card_title", "weapp_card_thumb_wrp",
    "weapp_card_ft", "weapp_card_logo", "pay", "pay__mask", "ct_geography_loc_tip",
    "subsc_context", "subsc_btn", "reset_btn", "icon_subsc", "weui-primary-loading",
    "weui-primary-loading__dot", "wxw-img", "mp-caret", "appmsg_poi_iframe", "cpc_iframe",
    "channels_iframe_wrp", "channels_iframe", "videosnap_video_iframe",
    "videosnap_live_iframe", "videosnap_image_iframe", "channels_live_iframe",
    "minishop_iframe_wrp", "minishop_iframe", "mp_profile_iframe",
    "mp_profile_iframe_wrp", "mp_search_iframe_wrp", "appmsg_search_iframe_wrp",
    "appmsg_search_iframe", "vote_area", "vote_iframe", "mp_vote_iframe_wrp",
    "mp_vote_iframe", "qqmusic_iframe", "blockquote_iframe", "blockquote_tips_iframe",
    "video_iframe", "shopcard_iframe", "topic_iframe", "weapp_app_iframe",
    "img_fail_iframe", "mp_miniprogram_iframe", "appmsg_cpslink_iframe",
    "js_editor_mpcpslink", "mp-cpslink-iframe-wrp", "mp_common_sticker_iframe",
    "mp_common_sticker_iframe_wrp", "mp_common_product_iframe", "mp_common_product_iframe_wrp",
    "mp_lottery_iframe_wrp", "mp_shopprofile_wrp", "new_cps_iframe", "redpackage_iframe",
    "mp_redpacket_iframe_wrp", "product_text_link", "clmusic_iframe", "clalbum_iframe",
    "mp_common_custom_iframe_wrp", "mp_common_custom_iframe", "mp_image_gallery_iframe",
]

CLASS_WHITE_LIST_REG: List[Pattern[str]] = [
    re.compile(r"^editor__content__"),
    re.compile(r"^wxw"),
    re.compile(r"^js_"),
    re.compile(r"^cps_inner"),
    re.compile(r"^bizsvr_"),
    re.compile(r"^code-snippet"),
    re.compile(r"^wx_(?!text_underline)"),
    re.compile(r"^wx-"),
    re.compile(r"^icon_emoji_"),
    re.compile(r"^custom_select_card"),
]

CLASS_BLACK_LIST: List[str] = [
    "wx-edui-media-wrp",
    "custom_select_card_wrp",
    "custom_select_card_selected",
]

# ==========================================
# 2.【已证实】id 属性剥离白名单标签（getfilterIdTagNameWhiteList）
# 静态分析未还原出具体标签集合，先留空，若发现例外标签请补充进来。
# ==========================================
ID_STRIP_TAG_WHITE_LIST: List[str] = []

# ==========================================
# 3. 参考信息（不作为强制过滤规则，仅用于系统提示词/文档展示）
# ==========================================
PASTE_MATCH_STYLE_WHITELIST_REF: List[str] = [
    "background-color", "color", "font-size", "font-family",
    "line-leight",  # 源码拼写如此，推测应为 line-height，疑似微信自身代码 bug
    "letter-spacing", "font-style", "font-weight", "text-decoration",
]

WORD_PASTE_FLATTEN_STYLE_WHITELIST_REF: List[str] = [
    "line-height", "max-width", "letter-spacing", "color", "font-weight", "box-sizing",
    "word-wrap", "-webkit-box-sizing", "margin", "padding", "font-family", "background-color",
    "white-space", "min-height", "font-size", "background-image", "background-clip",
    "background-position", "background-repeat", "background-size", "border", "bottom",
    "display", "float", "height", "left", "max-height", "min-width", "text-align",
    "text-decoration", "top", "position", "z-index", "visibility", "clear",
]

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
NEST_LIMIT = 20
NEST_SAFE = NEST_LIMIT - 2
SVG_LENGTH_LIMIT = 11000
CONSECUTIVE_BR_LIMIT = 10
RISKY_STYLE_PROPS = ["position", "z-index", "top", "left", "float", "display", "transform"]
BANNED_TAGS = {
    "style": ("WX-TAG-001", "内嵌 <style> 标签不受公众号文章 HTML 支持。", "将需要保留的受支持样式写到对应元素的 style 属性中。"),
    "link": ("WX-TAG-002", "外链样式表不会随公众号文章正文加载。", "移除 <link>，并将必要的受支持样式改为行内样式。"),
    "script": ("WX-TAG-003", "公众号文章正文不会执行 <script> 中的 JavaScript。", "移除脚本；将交互改为静态内容或公众号支持的组件。"),
    "iframe": ("WX-TAG-004", "普通 <iframe> 不能作为可移植的公众号文章正文内容。", "改用公众号支持的媒体、卡片或静态内容。"),
    "noscript": ("WX-TAG-005", "<noscript> 内容不能作为可靠的公众号文章正文。", "移除 <noscript>，直接保留需要展示的静态内容。"),
}
SVG_GRAPHIC_TAGS = {
    "animate", "animatemotion", "animatetransform", "circle", "clippath", "defs", "ellipse",
    "feblend", "fecolormatrix", "fecomponenttransfer", "fecomposite", "feconvolvematrix",
    "fediffuselighting", "fedisplacementmap", "fedistantlight", "fedropshadow", "feflood",
    "fefunca", "fefuncb", "fefuncg", "fefuncr", "fegaussianblur", "feimage", "femerge",
    "femergenode", "femorphology", "feoffset", "fepointlight", "fespecularlighting",
    "fespotlight", "fetile", "feturbulence", "filter", "foreignobject", "g", "image", "line",
    "lineargradient", "marker", "mask", "path", "pattern", "polygon", "polyline", "radialgradient",
    "rect", "set", "stop", "symbol", "text", "textpath", "tspan", "use",
}
EMPTY_NODE_EXEMPT_TAGS = re.compile(
    r"^(img|hr|svg|mp-common|iframe|cps|br|a|mp|video|audio|path|embed|rect|circle|ellipse|line|polyline|polygon|g|defs|use|text|tspan|animate|set)",
    re.IGNORECASE,
)

_ATTR_VALUE = r'(?:(?:"([^"]*?)")|(?:\'([^\']*?)\')|([^\'"\s=<>]*?))'
_STYLE_ATTR_RE = re.compile(r'(<[^<>]*?)\sstyle=' + _ATTR_VALUE + r'([\s/>])')
_CLASS_ATTR_RE = re.compile(r'(<[^<>]*?)\sclass=' + _ATTR_VALUE + r'([\s/>])')
_SVG_BLOCK_RE = re.compile(r'<svg[^>]*>([\s\S]*?)</svg>', re.IGNORECASE)
_BR_IN_TAG_RE = re.compile(r'<br[^>]*>', re.IGNORECASE)
_CONSECUTIVE_BR_RE = re.compile(r'(?:(?:<br\b[^<>]*>)\s*){10,}', re.IGNORECASE)
_APPLE_BR_RE = re.compile(r'<br class="Apple-interchange-newline">')
_ID_ATTR_RE = re.compile(r'(<(\w+)[^>]*)\sid="([^">]*)"([^>]*>)')
_TAG_RE = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?(/)?>')
_EMPTY_TAG_RE = re.compile(r'<([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*)>\s*</\1>')
_SVG_BLOCK_WITH_OFFSET_RE = re.compile(r'<svg\b[^>]*>[\s\S]*?</svg>', re.IGNORECASE)


@dataclass
class ComplianceDiagnostic:
    code: str
    severity: str
    path: str
    line: int
    column: int
    snippet: str
    message: str
    consequence: str
    suggestion: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "snippet": self.snippet,
            "message": self.message,
            "consequence": self.consequence,
            "suggestion": self.suggestion,
        }


@dataclass
class _HtmlElement:
    tag: str
    attrs: Dict[str, str]
    raw: str
    path: str
    line: int
    column: int
    html_depth: int
    inside_svg: bool
    child_counts: Dict[str, int] = field(default_factory=dict)


class _FragmentParser(HTMLParser):
    """A tolerant fragment parser used only to give audit hits a stable location."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.elements: List[_HtmlElement] = []
        self._stack: List[_HtmlElement] = []
        self._root_counts: Dict[str, int] = {}

    def _add_element(self, tag: str, attrs: List[tuple[str, Optional[str]]], is_self_closing: bool) -> None:
        tag = tag.lower()
        parent = self._stack[-1] if self._stack else None
        counts = parent.child_counts if parent else self._root_counts
        index = counts.get(tag, 0) + 1
        counts[tag] = index
        path_part = f"{tag}:nth-of-type({index})"
        path = f"{parent.path} > {path_part}" if parent else path_part
        inside_svg = bool(parent and (parent.inside_svg or parent.tag == "svg"))
        html_depth = 0 if inside_svg or tag == "svg" else (parent.html_depth if parent else 0) + 1
        line, column = self.getpos()
        element = _HtmlElement(
            tag=tag,
            attrs={name.lower(): value or "" for name, value in attrs},
            raw=self.get_starttag_text() or f"<{tag}>",
            path=path,
            line=line,
            column=column + 1,
            html_depth=html_depth,
            inside_svg=inside_svg,
        )
        self.elements.append(element)
        if not is_self_closing and tag not in VOID_TAGS:
            self._stack.append(element)

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        self._add_element(tag, attrs, is_self_closing=False)

    def handle_startendtag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        self._add_element(tag, attrs, is_self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                break


def _parse_html_fragment(html: str) -> List[_HtmlElement]:
    parser = _FragmentParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # The rest of the checker is regex tolerant; location metadata should not make it fail.
        pass
    return parser.elements


# ==========================================
# 4. 审计报告数据结构
# ==========================================
@dataclass
class ComplianceReport:
    removed_classes: List[str] = field(default_factory=list)
    kept_classes: List[str] = field(default_factory=list)
    removed_id_attributes: List[str] = field(default_factory=list)
    risk_style_hints: List[str] = field(default_factory=list)
    banned_tags: List[str] = field(default_factory=list)
    consecutive_br_runs: List[int] = field(default_factory=list)
    svg_id_attributes: List[str] = field(default_factory=list)
    image_issues: List[str] = field(default_factory=list)
    removed_svg_brs: int = 0
    has_svg: bool = False
    oversized_svg_blocks: List[int] = field(default_factory=list)
    max_nesting_depth: int = 0
    will_flatten_nesting: bool = False
    empty_node_suspects: List[str] = field(default_factory=list)
    diagnostics: List[ComplianceDiagnostic] = field(default_factory=list)

    def add_diagnostic(
        self,
        code: str,
        severity: str,
        element: Optional[_HtmlElement],
        message: str,
        consequence: str,
        suggestion: str,
        *,
        snippet: Optional[str] = None,
        path: Optional[str] = None,
        line: int = 0,
        column: int = 0,
    ) -> None:
        """Append a UI-ready audit record without making individual scanners know the schema."""
        self.diagnostics.append(
            ComplianceDiagnostic(
                code=code,
                severity=severity,
                path=path or (element.path if element else "文档"),
                line=element.line if element else line,
                column=element.column if element else column,
                snippet=(snippet if snippet is not None else (element.raw if element else ""))[:240],
                message=message,
                consequence=consequence,
                suggestion=suggestion,
            )
        )

    @property
    def has_error(self) -> bool:
        """对应已证实规则下的严重错误：会导致排版实际渲染崩溃/动效失效。"""
        return (
            self.will_flatten_nesting
            or bool(self.oversized_svg_blocks)
            or self.removed_svg_brs > 0
            or any(item.severity == "error" for item in self.diagnostics)
        )

    @property
    def has_warning(self) -> bool:
        """对应已证实规则下的警告：类名/id 会被剥离，但不至于让排版整体崩溃。"""
        return (
            bool(self.removed_classes)
            or bool(self.removed_id_attributes)
            or any(item.severity == "warning" for item in self.diagnostics)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "removedClasses": sorted(set(self.removed_classes)),
            "keptClasses": sorted(set(self.kept_classes)),
            "removedIdAttributes": self.removed_id_attributes,
            "riskStyleHints": self.risk_style_hints,
            "bannedTags": self.banned_tags,
            "consecutiveBrRuns": self.consecutive_br_runs,
            "svgIdAttributes": self.svg_id_attributes,
            "imageIssues": self.image_issues,
            "removedSvgBrs": self.removed_svg_brs,
            "hasSvg": self.has_svg,
            "oversizedSvgBlocks": self.oversized_svg_blocks,
            "maxNestingDepth": self.max_nesting_depth,
            "willFlattenNesting": self.will_flatten_nesting,
            "emptyNodeSuspects": self.empty_node_suspects,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "hasError": self.has_error,
            "hasWarning": self.has_warning,
        }


# ==========================================
# 5.【已证实】核心过滤函数（与 filter.js 逐字节核对一致）
# ==========================================

def filter_br(html: str, report: Optional[ComplianceReport] = None) -> str:
    """已证实：连续 br 折叠 + Apple 换行清理 + SVG 内部 br 剥离"""
    cleaned = html
    if _CONSECUTIVE_BR_RE.search(cleaned):
        cleaned = _CONSECUTIVE_BR_RE.sub(lambda match: _BR_IN_TAG_RE.search(match.group(0)).group(0), cleaned)
    cleaned = _APPLE_BR_RE.sub("", cleaned)

    def _clean_svg(match: "re.Match[str]") -> str:
        if report is not None:
            report.has_svg = True
        inner = match.group(1)
        br_count = len(_BR_IN_TAG_RE.findall(inner))
        if br_count > 0:
            if report is not None:
                report.removed_svg_brs += br_count
            return _BR_IN_TAG_RE.sub("", match.group(0))
        return match.group(0)

    return _SVG_BLOCK_RE.sub(_clean_svg, cleaned)


def format_redundancy_str(html: str) -> str:
    """已证实：formatRedundancyStr，清空 noscript/iframe 内的文本内容"""
    for tag in ("noscript", "iframe"):
        pattern = re.compile(r'(<' + tag + r'\s*[^<>]*?>)[^</]+?</' + tag + r'>')
        html = pattern.sub(r"\1</" + tag + ">", html)
    return html


def format_style(html: str) -> str:
    """已证实：formatStyle，规范化 style 属性的分号/引号写法"""
    def _norm(match: "re.Match[str]") -> str:
        prefix, dq, sq, unq, suffix = match.groups()
        style_val = dq or sq or unq or ""
        if not style_val:
            return match.group(0)
        style_val = style_val.replace("&quot;", '"')
        parts = [p.strip().replace('"', "&quot;") for p in style_val.split(";")]
        kept = [p for p in parts if p]
        return prefix + ' style="' + ";".join(kept) + ';"' + suffix

    return _STYLE_ATTR_RE.sub(_norm, html)


def filter_style_attr(html: str, css_attrs: Union[str, List[str]]) -> str:
    """
    已证实函数：filterStyleAttr，从 style 属性字符串中删除指定 CSS 属性。
    源码里唯一被证实的调用是 filter_style_attr(html, ["background-image"])（粘贴图片后清理）。
    不内置 position/z-index 等黑名单，由调用方指定要删除哪些属性。
    注意：`[$;]` 是照抄源码的字符类写法（并非"结尾锚点或分号"的意思），忠实保留这个细节。
    """
    attrs = [css_attrs] if isinstance(css_attrs, str) else list(css_attrs)

    def _strip(match: "re.Match[str]") -> str:
        prefix, style_val, suffix = match.group(1), match.group(2), match.group(3)
        for attr in attrs:
            item_re = re.compile(r'(^|;|\b)[^;]*' + re.escape(attr) + r'\s*:[^;]*[$;]')
            style_val = item_re.sub(r"\1", style_val)
        return prefix + style_val + suffix

    pattern = re.compile(r'(<[^<>]*?\sstyle=")([^"]*?)(")')
    return pattern.sub(_strip, html)


# 向后兼容别名（对应 wechat_format_rules_source.js 里的 filterStyleString）
filter_style_string = filter_style_attr


def remove_attribute(html: str, tag_attr_list: List[List[str]]) -> str:
    """
    已证实函数：removeAttribute（未在保存管线中找到默认调用证据，仅在需要按
    标签名+属性名主动删除属性时使用，不再默认用于剥离 id/data-*）。
    """
    for tag_name, attr_name in tag_attr_list:
        tag_part = "" if tag_name == "*" else tag_name
        pattern = re.compile(r'(<' + tag_part + r'[^<>]*?)\s' + attr_name + r'=' + _ATTR_VALUE + r'([\s/>])')
        while pattern.search(html):
            html = pattern.sub(lambda m: m.group(1) + m.group(5), html)
    return html


def format_class(
    html: str,
    white_list: Optional[List[str]] = None,
    white_list_reg: Optional[List[Pattern[str]]] = None,
    black_list: Optional[List[str]] = None,
    report: Optional[ComplianceReport] = None,
) -> str:
    """已证实：formatClass，按白名单/正则白名单/黑名单过滤 class"""
    white_list = CLASS_WHITE_LIST if white_list is None else white_list
    white_list_reg = CLASS_WHITE_LIST_REG if white_list_reg is None else white_list_reg
    black_list = CLASS_BLACK_LIST if black_list is None else black_list

    if not white_list and not white_list_reg and not black_list:
        return html

    def _filter(match: "re.Match[str]") -> str:
        prefix, dq, sq, unq, suffix = match.groups()
        class_val = dq or sq or unq or ""
        kept: List[str] = []
        for class_name in class_val.split(" "):
            if not class_name:
                continue
            if black_list and class_name in black_list:
                if report is not None:
                    report.removed_classes.append(class_name + " (黑名单)")
                continue
            if white_list and class_name in white_list:
                kept.append(class_name)
                if report is not None:
                    report.kept_classes.append(class_name)
                continue
            matched = False
            for reg in white_list_reg or []:
                if reg.search(class_name):
                    kept.append(class_name)
                    if report is not None:
                        report.kept_classes.append(class_name)
                    matched = True
                    break
            if not matched and report is not None:
                report.removed_classes.append(class_name)
        joined = " ".join(kept).strip()
        if joined:
            return prefix + ' class="' + joined + '"' + suffix
        return prefix + suffix

    return _CLASS_ATTR_RE.sub(_filter, html)


def filter_class(html: str, class_names: str) -> str:
    """已证实：filterClass，按空格分隔的类名列表整体移除"""
    if not class_names or not html:
        return html
    parts = class_names.split(" ")
    or_pattern = "|".join("(?:%s)" % p for p in parts)
    pattern = re.compile(
        r'(<[^<>]*?)\sclass=((?:"[^"]*' + or_pattern + r'[^"]*")|(?:\'[^\']*' + or_pattern + r"[^']*'))"
    )
    excluded = set((" " + class_names + " ").split())

    def _filter(match: "re.Match[str]") -> str:
        classes = re.sub(r"['\"]", "", match.group(2)).split(" ")
        kept = [c for c in classes if c and c not in excluded]
        return match.group(1) + ' class="' + " ".join(kept) + '"'

    return pattern.sub(_filter, html)


# ==========================================
# 6. 检查函数（明确区分"已证实规则"与"风险提示"）
# ==========================================

def _is_allowed_class(class_name: str, white_list: List[str], white_list_reg: List[Pattern[str]], black_list: List[str]) -> bool:
    if class_name in black_list:
        return False
    return class_name in white_list or any(reg.search(class_name) for reg in white_list_reg)


def audit_id_stripping(
    html: str,
    tag_white_list: Optional[List[str]] = None,
    report: Optional[ComplianceReport] = None,
    elements: Optional[List[_HtmlElement]] = None,
) -> List[Dict[str, str]]:
    """已证实规则：id 属性剥离审计，并为每个命中提供元素定位。"""
    white_list = {t.lower() for t in (tag_white_list or ID_STRIP_TAG_WHITE_LIST)}
    found: List[Dict[str, str]] = []
    for element in elements if elements is not None else _parse_html_fragment(html):
        id_value = element.attrs.get("id")
        if id_value is None or element.tag in white_list:
            continue
        found.append({"tag": element.tag, "id": id_value})
        if report is not None:
            report.removed_id_attributes.append(f'<{element.tag} id="{id_value}">')
            report.add_diagnostic(
                "WX-ATTR-001",
                "warning",
                element,
                "id 属性会在公众号编辑器处理时被剥离。",
                "依赖该 id 的 CSS、锚点或 SVG 动画触发器会失效。",
                "不要依赖正文 HTML 的 id；SVG 动画请使用不依赖外部 id 的触发方式。",
            )
            if element.inside_svg or element.tag == "svg":
                report.svg_id_attributes.append(f'<{element.tag} id="{id_value}">')
    return found


def _split_inline_style(style: str) -> List[tuple[str, str]]:
    """Split inline CSS without treating semicolons inside strings or url() as declarations."""
    declarations: List[str] = []
    start = 0
    quote = ""
    parentheses = 0
    for index, char in enumerate(style):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            parentheses += 1
        elif char == ")":
            parentheses = max(0, parentheses - 1)
        elif char == ";" and parentheses == 0:
            declarations.append(style[start:index])
            start = index + 1
    declarations.append(style[start:])

    parsed: List[tuple[str, str]] = []
    for declaration in declarations:
        prop, separator, value = declaration.partition(":")
        prop = prop.strip().lower()
        if separator and prop:
            parsed.append((prop, value.strip().lower()))
    return parsed


def _record_style_risk(
    report: Optional[ComplianceReport],
    hints: List[str],
    element: _HtmlElement,
    code: str,
    prop: str,
    value: str,
    message: str,
    consequence: str,
    suggestion: str,
) -> None:
    hint = f'{prop}:{value} in "{element.attrs.get("style", "").strip()}"'
    hints.append(prop)
    if report is not None:
        report.risk_style_hints.append(hint)
        report.add_diagnostic(code, "warning", element, message, consequence, suggestion)


def scan_risky_inline_styles(
    html: str,
    report: Optional[ComplianceReport] = None,
    elements: Optional[List[_HtmlElement]] = None,
) -> List[str]:
    """Detect CSS features that are fragile in the public-account editor without claiming they are always stripped."""
    hints: List[str] = []
    for element in elements if elements is not None else _parse_html_fragment(html):
        style = element.attrs.get("style")
        if not style:
            continue
        for prop, value in _split_inline_style(style):
            if prop == "position" and value in {"absolute", "fixed", "sticky"}:
                _record_style_risk(
                    report, hints, element, "WX-CSS-001", prop, value,
                    f"检测到 position:{value}，该定位方式在公众号正文中兼容性不稳定。",
                    "不同客户端可能忽略定位或导致元素重叠、脱离预期布局。",
                    "改用普通文档流、margin/padding 和 text-align 完成布局。",
                )
            elif prop in {"z-index", "top", "left", "float"}:
                _record_style_risk(
                    report, hints, element, "WX-CSS-002", prop, value,
                    f"检测到 {prop} 定位相关样式。",
                    "公众号客户端的样式处理可能改变层叠或定位结果。",
                    "避免依赖层叠、偏移或浮动；使用普通文档流布局。",
                )
            elif (prop == "display" and value == "grid") or prop.startswith("grid-"):
                _record_style_risk(
                    report, hints, element, "WX-CSS-003", prop, value,
                    "检测到 CSS Grid 布局。",
                    "部分公众号客户端不支持或会降级 Grid，列布局可能错乱。",
                    "改用支持范围更广的块级布局和行内样式。",
                )
            elif prop == "transform":
                _record_style_risk(
                    report, hints, element, "WX-CSS-004", prop, value,
                    "检测到 transform 样式。",
                    "变形、位移或缩放效果在公众号客户端可能失效或影响文字排版。",
                    "优先使用原始尺寸和普通间距，避免依赖 transform 定位。",
                )
    return hints


def scan_banned_tags(elements: List[_HtmlElement], report: ComplianceReport) -> None:
    for element in elements:
        rule = BANNED_TAGS.get(element.tag)
        if rule is None:
            continue
        code, message, suggestion = rule
        report.banned_tags.append(element.tag)
        report.add_diagnostic(
            code,
            "error",
            element,
            message,
            "该节点会被清理、忽略或无法按网页方式运行，正文效果不可预测。",
            suggestion,
        )


def scan_class_removal_diagnostics(elements: List[_HtmlElement], report: ComplianceReport) -> None:
    for element in elements:
        class_value = element.attrs.get("class")
        if not class_value:
            continue
        for class_name in class_value.split():
            if not _is_allowed_class(class_name, CLASS_WHITE_LIST, CLASS_WHITE_LIST_REG, CLASS_BLACK_LIST):
                report.add_diagnostic(
                    "WX-ATTR-002",
                    "warning",
                    element,
                    f'自定义 class "{class_name}" 不在公众号编辑器白名单内。',
                    "该 class 会被清理，依赖它的样式或脚本选择器会失效。",
                    "将必要的受支持样式直接写入 style 属性，不要依赖自定义 class。",
                )


def scan_consecutive_brs(html: str, elements: List[_HtmlElement], report: ComplianceReport) -> None:
    br_elements = [element for element in elements if element.tag == "br"]
    for match in _CONSECUTIVE_BR_RE.finditer(html):
        count = len(_BR_IN_TAG_RE.findall(match.group(0)))
        if count < CONSECUTIVE_BR_LIMIT:
            continue
        report.consecutive_br_runs.append(count)
        element = next((item for item in br_elements if item.raw in match.group(0)), None)
        report.add_diagnostic(
            "WX-HTML-001",
            "warning",
            element,
            f"检测到连续 {count} 个 <br> 标签。",
            "编辑器可能压缩连续换行，依赖空行堆叠形成的间距会在发布后变化。",
            "使用段落和受支持的 margin/padding 控制间距，避免连续 <br>。",
            snippet=match.group(0),
        )


def scan_svg_animation_rules(html: str, elements: List[_HtmlElement], report: ComplianceReport) -> None:
    svg_elements = [element for element in elements if element.tag == "svg"]
    if not svg_elements:
        return

    report.has_svg = True
    for match in _SVG_BLOCK_WITH_OFFSET_RE.finditer(html):
        svg = next((element for element in svg_elements if element.raw in match.group(0)), svg_elements[0])
        br_count = len(_BR_IN_TAG_RE.findall(match.group(0)))
        if br_count:
            report.add_diagnostic(
                "WX-SVG-001",
                "error",
                svg,
                f"SVG 内包含 {br_count} 个 <br> 标签。",
                "公众号处理 SVG 时会删除这些 <br>，SVG 结构或文本布局会改变。",
                "移除 SVG 内的 <br>，用 SVG 的 text/tspan 元素表达换行。",
                snippet=match.group(0),
            )

        for begin_match in re.finditer(r'\bbegin\s*=\s*(["\'])(.*?)\1', match.group(0), re.IGNORECASE):
            begin_value = begin_match.group(2).strip()
            if not re.search(r'(^|;|\s)[A-Za-z_][\w:.-]*\.click(?:[+\-]\d+(?:\.\d+)?s)?(?:;|$)', begin_value):
                continue
            report.add_diagnostic(
                "WX-SVG-002",
                "error",
                svg,
                f'检测到跨元素 SVG 动画触发器 begin="{begin_value}"。',
                "触发器依赖 id，而公众号会剥离 SVG 的 id 属性，动画将无法启动。",
                '改为当前元素自触发的 begin="click"，并移除跨元素 id 依赖。',
                snippet=begin_match.group(0),
            )


def scan_image_rules(elements: List[_HtmlElement], report: ComplianceReport) -> None:
    for element in elements:
        if element.tag != "img":
            continue
        style_props = {
            prop: value.replace("!important", "").strip()
            for prop, value in _split_inline_style(element.attrs.get("style", ""))
        }
        if "alt" not in element.attrs:
            issue = "图片缺少 alt 文本"
            report.image_issues.append(issue)
            report.add_diagnostic(
                "WX-IMG-001",
                "warning",
                element,
                issue + "。",
                "图片加载失败或需要辅助阅读时，没有可替代的说明文字。",
                "为 img 添加能概括图片内容的 alt 属性；装饰图可使用 alt=\"\"。",
            )

        responsive_requirements = {
            "max-width": "100%",
            "height": "auto",
            "display": "block",
        }
        missing = [
            f"{prop}:{expected}"
            for prop, expected in responsive_requirements.items()
            if style_props.get(prop) != expected
        ]
        if missing:
            issue = "图片缺少响应式样式：" + "、".join(missing)
            report.image_issues.append(issue)
            report.add_diagnostic(
                "WX-IMG-002",
                "warning",
                element,
                issue + "。",
                "在不同屏幕宽度下，图片可能溢出、变形或产生基线空隙。",
                "在 style 中添加 max-width:100%; height:auto; display:block;。",
            )

        has_fixed_style_dimension = any(
            value and value != "auto" and not value.endswith("%")
            for value in (style_props.get("width"), style_props.get("height"))
        )
        if "width" in element.attrs or "height" in element.attrs or has_fixed_style_dimension:
            issue = "图片使用固定尺寸"
            report.image_issues.append(issue)
            report.add_diagnostic(
                "WX-IMG-003",
                "warning",
                element,
                issue + "。",
                "固定尺寸在窄屏设备上可能溢出或导致比例失真。",
                "保留 max-width:100% 和 height:auto，避免依赖固定宽高。",
            )


def check_nesting_depth(
    html: str,
    report: Optional[ComplianceReport] = None,
    elements: Optional[List[_HtmlElement]] = None,
) -> int:
    """
    已证实规则：Word 粘贴嵌套深度限制（clear_dom.js）。
    节点深度或连续同类子节点达到 20 时触发扁平化。用通用标签栈扫描器估算 HTML
    最大嵌套深度（忽略 void 元素/自闭合标签，且不把 SVG 内部图形标签计入层级）。
    """
    depth = 0
    max_depth = 0
    pos = 0
    length = len(html)
    while pos < length:
        match = _TAG_RE.search(html, pos)
        if not match:
            break
        closing = match.group(1) == "/"
        tag_name = match.group(2).lower()
        self_closing = bool(match.group(3))
        next_pos = match.end()

        if tag_name == "svg":
            if not closing and not self_closing:
                svg_end = html.find("</svg>", next_pos)
                if svg_end != -1:
                    next_pos = svg_end + len("</svg>")
            pos = next_pos
            continue

        if tag_name in VOID_TAGS or self_closing:
            pos = next_pos
            continue

        if closing:
            depth = max(0, depth - 1)
        else:
            depth += 1
            max_depth = max(max_depth, depth)
        pos = next_pos

    if report is not None:
        report.max_nesting_depth = max_depth
        report.will_flatten_nesting = max_depth >= NEST_LIMIT
        deepest = next((element for element in elements or [] if element.html_depth == max_depth), None)
        if max_depth >= NEST_LIMIT:
            report.add_diagnostic(
                "WX-HTML-002",
                "error",
                deepest,
                f"HTML 最大嵌套深度为 {max_depth} 层，达到 Word 粘贴扁平化阈值。",
                "从 Word 粘贴时编辑器会扁平化节点，结构和排版可能被重写。",
                f"将结构缩减到 {NEST_SAFE} 层以内，避免依赖深层容器。",
            )
        elif max_depth > NEST_SAFE:
            report.add_diagnostic(
                "WX-HTML-003",
                "warning",
                deepest,
                f"HTML 最大嵌套深度为 {max_depth} 层，已超过建议安全线。",
                "从 Word 粘贴或后续清理时可能使其达到扁平化阈值。",
                f"建议将嵌套深度控制在 {NEST_SAFE} 层以内。",
            )
    return max_depth


def check_svg_serialized_length(
    html: str,
    report: Optional[ComplianceReport] = None,
    elements: Optional[List[_HtmlElement]] = None,
) -> List[int]:
    """已证实规则：单个 SVG 序列化长度 >= 11000 字符会被替换为 <embed>"""
    oversized: List[int] = []
    svg_elements = [element for element in elements or [] if element.tag == "svg"]
    for index, match in enumerate(_SVG_BLOCK_WITH_OFFSET_RE.finditer(html)):
        if report is not None:
            report.has_svg = True
        matched_len = len(match.group(0))
        if matched_len >= SVG_LENGTH_LIMIT:
            oversized.append(matched_len)
            if report is not None:
                report.oversized_svg_blocks.append(matched_len)
                report.add_diagnostic(
                    "WX-SVG-003",
                    "error",
                    svg_elements[index] if index < len(svg_elements) else None,
                    f"SVG 序列化长度为 {matched_len} 字符，达到 11000 字符硬性阈值。",
                    "该 SVG 会被公众号替换为 <embed>，图形和动效都无法按原样保留。",
                    "删除冗余属性和路径，拆分或简化 SVG，使单个 SVG 小于 11000 字符。",
                    snippet=match.group(0),
                )
    return oversized


def scan_empty_node_suspects(
    html: str,
    report: Optional[ComplianceReport] = None,
    elements: Optional[List[_HtmlElement]] = None,
) -> List[str]:
    """
    弱提示（非确定规则）：疑似冗余空节点扫描。
    真实的 deleteRedundantNode 触发条件是"父节点子元素数 > 20 且连续 15+ 个空子节点"，
    这里只做单节点级别的启发式提示，命中不代表一定会被清理。
    """
    suspects: List[str] = []
    for match in _EMPTY_TAG_RE.finditer(html):
        tag_name = match.group(1)
        attrs = match.group(2) or ""
        if tag_name.lower() in SVG_GRAPHIC_TAGS or EMPTY_NODE_EXEMPT_TAGS.match(tag_name):
            continue
        if "background-image" in attrs:
            continue
        suspects.append(match.group(0))
        if report is not None:
            report.empty_node_suspects.append(match.group(0)[:80])
            element = next((item for item in elements or [] if item.tag.lower() == tag_name.lower()), None)
            report.add_diagnostic(
                "WX-HTML-004",
                "info",
                element,
                f"检测到疑似冗余空节点 <{tag_name}>。",
                "当父节点中存在大量连续空节点时，编辑器可能清理这些节点。",
                "确认该节点是否承担布局职责；无意义的空节点应移除。",
                snippet=match.group(0),
            )
    return suspects


# ==========================================
# 7. 对外主入口
# ==========================================

def run_compliance_check(html: str) -> ComplianceReport:
    """
    跑一遍全部审计逻辑并返回结构化报告，供 FastAPI `/api/compliance/check` 接口
    以及多轮对话编辑 Agent 的 `check_compliance` 工具共同调用。
    与 `wechat_format_rules_source.js` 的 `runCheck()` 规则保持一致。
    """
    report = ComplianceReport()

    elements = _parse_html_fragment(html)
    scan_banned_tags(elements, report)
    scan_class_removal_diagnostics(elements, report)
    scan_consecutive_brs(html, elements, report)
    scan_risky_inline_styles(html, report=report, elements=elements)
    scan_image_rules(elements, report)

    cleaned = filter_br(html, report)
    cleaned = format_style(cleaned)
    format_class(cleaned, report=report)
    audit_id_stripping(html, report=report, elements=elements)
    scan_svg_animation_rules(html, elements, report)
    check_nesting_depth(html, report=report, elements=elements)
    check_svg_serialized_length(html, report=report, elements=elements)
    scan_empty_node_suspects(html, report=report, elements=elements)

    return report


def _print_cli_report(html: str) -> int:
    """轻量 CLI 入口，方便在没有 Node.js 环境时用 Python 做同样的校验。"""
    report = run_compliance_check(html)
    data = report.to_dict()

    print("==================================================")
    print("微信公众号排版规范校验工具（Python 版）")
    print("==================================================")

    print("\n[已证实 1/6] class 白名单过滤审计:")
    if data["removedClasses"]:
        print(f"  警告: 以下自定义类名将被剔除: {', '.join(data['removedClasses'])}")
    else:
        print("  通过: 所有类名均在微信官方白名单内，或无类名修饰。")

    print("\n[已证实 2/6] id 属性剥离审计:")
    if data["removedIdAttributes"]:
        print(f"  警告: 检测到将被剥离的 id 属性共 {len(data['removedIdAttributes'])} 处: {data['removedIdAttributes'][:5]}")
    else:
        print("  通过: 未检测到会被剥离的 id 属性。")

    print(f"\n[已证实 3/6] Word 粘贴嵌套深度审计（限制 {NEST_LIMIT} 层，安全线 {NEST_SAFE} 层）:")
    if data["willFlattenNesting"]:
        print(f"  错误: 最大嵌套深度 {data['maxNestingDepth']} 层，已达到/超过扁平化阈值。")
    elif data["maxNestingDepth"] > NEST_SAFE:
        print(f"  警告: 最大嵌套深度 {data['maxNestingDepth']} 层，超过建议安全线。")
    else:
        print(f"  通过: 最大嵌套深度为 {data['maxNestingDepth']} 层。")

    print("\n[已证实 4/6] SVG 序列化长度审计（>=11000 字符会被替换为 <embed>）:")
    if data["oversizedSvgBlocks"]:
        print(f"  错误: {len(data['oversizedSvgBlocks'])} 个 SVG 块超过长度限制: {data['oversizedSvgBlocks']}")
    elif data["hasSvg"]:
        print("  通过: 检测到 SVG，长度均在限制内。")
    else:
        print("  信息: 未包含 SVG 元素。")

    print("\n[已证实 5/6] SVG 内部 <br> 审计:")
    if data["removedSvgBrs"] > 0:
        print(f"  错误: SVG 内部包含 {data['removedSvgBrs']} 个 <br>，会被强制剥离。")
    else:
        print("  通过: SVG 块内部未发现非法 <br>。")

    print("\n[已证实 6/6] 疑似冗余空节点扫描（弱提示）:")
    if data["emptyNodeSuspects"]:
        print(f"  提示: 发现 {len(data['emptyNodeSuspects'])} 处疑似空标签: {data['emptyNodeSuspects'][:5]}")
    else:
        print("  通过: 未发现明显的冗余空标签。")

    print("\n[未证实规则/风险提示] 定位类样式使用扫描:")
    if data["riskStyleHints"]:
        unique_props = sorted({h.split(" in ")[0] for h in data["riskStyleHints"]})
        print(f"  提示: 检测到使用了 {', '.join(unique_props)} 等定位/浮动样式，仅供参考。")
    else:
        print("  通过: 未检测到 position:absolute 等定位样式使用。")

    print("\n==================================================")
    if data["hasError"]:
        print("结论: 存在已证实规则下的严重错误，请修复后重新校验。")
        return 1
    if data["hasWarning"]:
        print("结论: 存在潜在警告，请确认是否符合设计意图。")
        return 0
    print("结论: 已证实规则均通过。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python wechat_compliance.py <html_file_path>")
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        content = f.read()
    sys.exit(_print_cli_report(content))
