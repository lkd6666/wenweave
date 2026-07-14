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
NEST_LIMIT = 10
NEST_SAFE = NEST_LIMIT - 2
SVG_LENGTH_LIMIT = 11000
RISKY_STYLE_PROPS = ["position", "z-index", "top", "left", "float"]
EMPTY_NODE_EXEMPT_TAGS = re.compile(
    r"^(img|hr|svg|mp-common|iframe|cps|br|a|mp|video|audio|path|embed)", re.IGNORECASE
)

_ATTR_VALUE = r'(?:(?:"([^"]*?)")|(?:\'([^\']*?)\')|([^\'"\s=<>]*?))'
_STYLE_ATTR_RE = re.compile(r'(<[^<>]*?)\sstyle=' + _ATTR_VALUE + r'([\s/>])')
_CLASS_ATTR_RE = re.compile(r'(<[^<>]*?)\sclass=' + _ATTR_VALUE + r'([\s/>])')
_SVG_BLOCK_RE = re.compile(r'<svg[^>]*>([\s\S]*?)</svg>', re.IGNORECASE)
_BR_IN_TAG_RE = re.compile(r'<br[^>]*>', re.IGNORECASE)
_CONSECUTIVE_BR_RE = re.compile(r'(<br[^<>]*>\s*<br[^<>]*>){10,}')
_APPLE_BR_RE = re.compile(r'<br class="Apple-interchange-newline">')
_ID_ATTR_RE = re.compile(r'(<(\w+)[^>]*)\sid="([^">]*)"([^>]*>)')
_TAG_RE = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?(/)?>')
_EMPTY_TAG_RE = re.compile(r'<([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*)>\s*</\1>')


# ==========================================
# 4. 审计报告数据结构
# ==========================================
@dataclass
class ComplianceReport:
    removed_classes: List[str] = field(default_factory=list)
    kept_classes: List[str] = field(default_factory=list)
    removed_id_attributes: List[str] = field(default_factory=list)
    risk_style_hints: List[str] = field(default_factory=list)
    removed_svg_brs: int = 0
    has_svg: bool = False
    oversized_svg_blocks: List[int] = field(default_factory=list)
    max_nesting_depth: int = 0
    will_flatten_nesting: bool = False
    empty_node_suspects: List[str] = field(default_factory=list)

    @property
    def has_error(self) -> bool:
        """对应已证实规则下的严重错误：会导致排版实际渲染崩溃/动效失效。"""
        return self.will_flatten_nesting or bool(self.oversized_svg_blocks) or self.removed_svg_brs > 0

    @property
    def has_warning(self) -> bool:
        """对应已证实规则下的警告：类名/id 会被剥离，但不至于让排版整体崩溃。"""
        return bool(self.removed_classes) or bool(self.removed_id_attributes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "removedClasses": sorted(set(self.removed_classes)),
            "keptClasses": sorted(set(self.kept_classes)),
            "removedIdAttributes": self.removed_id_attributes,
            "riskStyleHints": self.risk_style_hints,
            "removedSvgBrs": self.removed_svg_brs,
            "hasSvg": self.has_svg,
            "oversizedSvgBlocks": self.oversized_svg_blocks,
            "maxNestingDepth": self.max_nesting_depth,
            "willFlattenNesting": self.will_flatten_nesting,
            "emptyNodeSuspects": self.empty_node_suspects,
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
        cleaned = _CONSECUTIVE_BR_RE.sub(r"\1", cleaned)
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

def audit_id_stripping(
    html: str, tag_white_list: Optional[List[str]] = None, report: Optional[ComplianceReport] = None
) -> List[Dict[str, str]]:
    """已证实规则：id 属性剥离审计，正则来自旧版 getEditorData"""
    white_list = {t.lower() for t in (tag_white_list or ID_STRIP_TAG_WHITE_LIST)}
    found: List[Dict[str, str]] = []
    for match in _ID_ATTR_RE.finditer(html):
        tag_name = match.group(2).lower()
        id_value = match.group(3)
        if tag_name in white_list:
            continue
        found.append({"tag": tag_name, "id": id_value})
        if report is not None:
            report.removed_id_attributes.append(f'<{tag_name} id="{id_value}">')
    return found


def scan_risky_inline_styles(html: str, report: Optional[ComplianceReport] = None) -> List[str]:
    """
    未证实规则 / 风险提示：定位类样式使用扫描。
    没有找到 position/z-index/top/left/float 会被强制过滤的调用证据，仅供参考。
    """
    pattern = re.compile(r'<[^<>]*?\sstyle="([^"]*?)"[^<>]*>')
    hints: List[str] = []
    for match in pattern.finditer(html):
        style_val = match.group(1)
        for prop in RISKY_STYLE_PROPS:
            if re.search(r'(^|;|\s)' + re.escape(prop) + r'\s*:', style_val, re.IGNORECASE):
                hints.append(prop)
                if report is not None:
                    report.risk_style_hints.append(f'{prop} in "{style_val.strip()}"')
    return hints


def check_nesting_depth(html: str, report: Optional[ComplianceReport] = None) -> int:
    """
    已证实规则：嵌套深度限制（editor_filter.js deleteNestNode）。
    上限 10 层触发扁平化，扁平化收敛目标为 8 层。用通用标签栈扫描器估算 HTML
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
    return max_depth


def check_svg_serialized_length(html: str, report: Optional[ComplianceReport] = None) -> List[int]:
    """已证实规则：单个 SVG 序列化长度 >= 11000 字符会被替换为 <embed>"""
    pattern = re.compile(r'<svg[^>]*>[\s\S]*?</svg>', re.IGNORECASE)
    oversized: List[int] = []
    for match in pattern.finditer(html):
        if report is not None:
            report.has_svg = True
        matched_len = len(match.group(0))
        if matched_len >= SVG_LENGTH_LIMIT:
            oversized.append(matched_len)
            if report is not None:
                report.oversized_svg_blocks.append(matched_len)
    return oversized


def scan_empty_node_suspects(html: str, report: Optional[ComplianceReport] = None) -> List[str]:
    """
    弱提示（非确定规则）：疑似冗余空节点扫描。
    真实的 deleteRedundantNode 触发条件是"父节点子元素数 > 20 且连续 15+ 个空子节点"，
    这里只做单节点级别的启发式提示，命中不代表一定会被清理。
    """
    suspects: List[str] = []
    for match in _EMPTY_TAG_RE.finditer(html):
        tag_name = match.group(1)
        attrs = match.group(2) or ""
        if EMPTY_NODE_EXEMPT_TAGS.match(tag_name):
            continue
        if "background-image" in attrs:
            continue
        suspects.append(match.group(0))
        if report is not None:
            report.empty_node_suspects.append(match.group(0)[:80])
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

    cleaned = filter_br(html, report)
    cleaned = format_style(cleaned)
    format_class(cleaned, report=report)
    audit_id_stripping(cleaned, report=report)
    scan_risky_inline_styles(cleaned, report=report)
    check_nesting_depth(cleaned, report=report)
    check_svg_serialized_length(cleaned, report=report)
    scan_empty_node_suspects(cleaned, report=report)

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

    print("\n[已证实 3/6] 嵌套深度审计（限制 10 层，安全线 8 层）:")
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
