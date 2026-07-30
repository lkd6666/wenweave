/**
 * 微信公众号 HTML/SVG 排版规范自动检查工具 (wechat_format_rules_source.js)
 *
 * 本工具基于对 mp.weixin.qq.com 编辑器前端资源包（旧版 UEditor 管线 + 灰度 ProseMirror
 * 编辑器管线）的静态逆向分析构建。所有规则分为两类，报告中会明确区分：
 *
 *   【已证实规则】在压缩后的源码中找到了具体的函数实现 / 正则 / 真实调用点，可信度高，
 *                 直接来自 `@tencent/mp-common-appmsg-content`（editor/plugin/filter.js）、
 *                 旧版 getEditorData、editor_filter.js（deleteNestNode/deleteRedundantNode）
 *                 等模块。
 *   【未证实规则】只是行业经验或历史文档的推测，静态分析没有找到直接的调用证据（例如
 *                 "定位样式会被过滤"这一说法，源码中 filterStyleAttr 唯一被证实的调用只有
 *                 针对粘贴图片的 background-image，并没有找到 position/z-index 等黑名单调用）。
 *                 这类规则在报告中降级为"风险提示"，不再当作确定会发生的过滤结果。
 *
 * 运行方式:
 *   node wechat_format_rules_source.js <your_html_file.html>
 */

const fs = require('fs');
const path = require('path');

// ==========================================
// 1.【已证实】class 白名单 / 正则 / 黑名单
// 来源：@tencent/mp-common-appmsg-content -> editor/plugin/filter.js
// 与运行时 setClassWhiteListRules() 的调用逐字核对（含运行时 push 的
// mp_common_custom_iframe_wrp / mp_common_custom_iframe，已合并进数组本身）
// ==========================================
const classWhiteList = [
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
  "mp_common_custom_iframe_wrp", "mp_common_custom_iframe", "mp_image_gallery_iframe"
];

const classWhiteListReg = [
  /^editor__content__/,
  /^wxw/,
  /^js_/,
  /^cps_inner/,
  /^bizsvr_/,
  /^code-snippet/,
  /^wx_(?!text_underline)/,
  /^wx-/,
  /^icon_emoji_/,
  /^custom_select_card/
];

// 已核实 blackList 的真实取值：pluginParentClass / parentClass / selectedClass
const classBlackList = [
  "wx-edui-media-wrp",
  "custom_select_card_wrp",
  "custom_select_card_selected"
];

// ==========================================
// 2.【已证实】id 属性剥离规则
// 真实位置：template_edit_fe.e4e63001.js.下载 ~61993（旧版 getEditorData）
// 真实正则：/(<\w+[^>]*)\sid="([^">]*)"([^>]*>)/g
// 该正则只处理双引号 id，且存在"插件标签白名单例外"（getfilterIdTagNameWhiteList）：
// 命中白名单标签名的 id 会被保留。静态分析未能还原该白名单的具体标签集合，这里先留空数组，
// 如果后续在业务中发现某类自定义标签的 id 被保留，请把标签名补充到下面数组中。
// 另外，灰度版 ProseMirror 编辑器的 postprocess 是否重复执行此正则尚未证实，
// 保守起见仍按"会被剥离"处理并提示。
// ==========================================
const idStripTagWhiteList = [];

// ==========================================
// 3. 参考信息（不作为强制过滤规则，仅用于生成排版指导文案/系统提示词时引用）
// ==========================================

// 粘贴时"匹配目标格式"选项使用的样式属性白名单（源码变量名 A）
// 位置：appmsg_edit_v2_gray_fe.704669e7.js.下载 ~476613
// 注意：源码把 line-height 拼成了 "line-leight"，这里保留真实拼写以便溯源；
// 这份名单只在用户粘贴内容并主动选择"匹配目标格式"时生效，不是通用保存态强制过滤规则。
const PASTE_MATCH_STYLE_WHITELIST_REF = [
  "background-color", "color", "font-size", "font-family",
  "line-leight" /* 源码拼写如此，推测应为 line-height，疑似微信自身代码 bug */,
  "letter-spacing", "font-style", "font-weight", "text-decoration"
];

// Word 粘贴深度扁平化专用样式白名单（clear_dom.js styleKey）
// 位置：li~web1_web2_common_fe.a837e4e6.js.下载 ~126700
// 仅在"从 Word 粘贴"场景、且节点深度或连续同类子节点数 >= 20 触发扁平化时才会用到，
// 同样不是通用保存态过滤规则。
const WORD_PASTE_FLATTEN_STYLE_WHITELIST_REF = [
  "line-height", "max-width", "letter-spacing", "color", "font-weight", "box-sizing",
  "word-wrap", "-webkit-box-sizing", "margin", "padding", "font-family", "background-color",
  "white-space", "min-height", "font-size", "background-image", "background-clip",
  "background-position", "background-repeat", "background-size", "border", "bottom",
  "display", "float", "height", "left", "max-height", "min-width", "text-align",
  "text-decoration", "top", "position", "z-index", "visibility", "clear"
];

// ==========================================
// 4. 自动检查审计日志收集器
// ==========================================
let auditLog = {
  removedClasses: [],
  keptClasses: [],
  removedIdAttributes: [],   // 已证实规则
  riskStyleHints: [],        // 未证实规则（风险提示，不代表一定被过滤）
  bannedTags: [],
  consecutiveBrRuns: [],
  svgIdAttributes: [],
  imageIssues: [],
  diagnostics: [],
  removedSvgBrs: 0,
  hasSvg: false,
  oversizedSvgBlocks: [],    // 已证实规则：单个 SVG 序列化长度 >= 11000 会被替换为 <embed>
  maxNestingDepth: 0,        // 已证实规则：嵌套深度
  willFlattenNesting: false,
  emptyNodeSuspects: []      // 弱提示：真实触发条件更复杂（见 scanEmptyNodeSuspects 注释）
};

function resetAuditLog() {
  auditLog = {
    removedClasses: [],
    keptClasses: [],
    removedIdAttributes: [],
    riskStyleHints: [],
    bannedTags: [],
    consecutiveBrRuns: [],
    svgIdAttributes: [],
    imageIssues: [],
    diagnostics: [],
    removedSvgBrs: 0,
    hasSvg: false,
    oversizedSvgBlocks: [],
    maxNestingDepth: 0,
    willFlattenNesting: false,
    emptyNodeSuspects: []
  };
  return auditLog;
}

function addDiagnostic(code, severity, message, consequence, suggestion, snippet) {
  auditLog.diagnostics.push({
    code: code,
    severity: severity,
    path: '文档',
    snippet: (snippet || '').slice(0, 240),
    message: message,
    consequence: consequence,
    suggestion: suggestion
  });
}

function scanBannedTags(html) {
  var rules = {
    style: ['WX-TAG-001', '内嵌 <style> 标签不受公众号文章 HTML 支持。'],
    link: ['WX-TAG-002', '外链样式表不会随公众号文章正文加载。'],
    script: ['WX-TAG-003', '公众号文章正文不会执行 <script> 中的 JavaScript。'],
    iframe: ['WX-TAG-004', '普通 <iframe> 不能作为可移植的公众号文章正文内容。'],
    noscript: ['WX-TAG-005', '<noscript> 内容不能作为可靠的公众号文章正文。']
  };
  Object.keys(rules).forEach(function(tag) {
    var regex = new RegExp('<' + tag + '\\b[^>]*>', 'gi');
    var match;
    while ((match = regex.exec(html)) !== null) {
      auditLog.bannedTags.push(tag);
      addDiagnostic(rules[tag][0], 'error', rules[tag][1], '该节点会被清理、忽略或无法按网页方式运行，正文效果不可预测。', '移除该标签，并使用公众号正文支持的静态内容或行内样式。', match[0]);
    }
  });
}

function scanConsecutiveBrs(html) {
  var regex = /(?:(?:<br\b[^<>]*>)\s*){10,}/gi;
  var match;
  while ((match = regex.exec(html)) !== null) {
    var count = (match[0].match(/<br\b[^<>]*>/gi) || []).length;
    auditLog.consecutiveBrRuns.push(count);
    addDiagnostic('WX-HTML-001', 'warning', '检测到连续 ' + count + ' 个 <br> 标签。', '编辑器可能压缩连续换行，依赖空行堆叠形成的间距会在发布后变化。', '使用段落和受支持的 margin/padding 控制间距，避免连续 <br>。', match[0]);
  }
}

function scanSvgAnimationRules(html) {
  var blockRegex = /<svg\b[^>]*>[\s\S]*?<\/svg>/gi;
  var block;
  while ((block = blockRegex.exec(html)) !== null) {
    var svg = block[0];
    var idRegex = /\bid\s*=\s*(["'])(.*?)\1/gi;
    var idMatch;
    while ((idMatch = idRegex.exec(svg)) !== null) {
      auditLog.svgIdAttributes.push(idMatch[0]);
    }
    var brCount = (svg.match(/<br\b[^>]*>/gi) || []).length;
    if (brCount) {
      addDiagnostic('WX-SVG-001', 'error', 'SVG 内包含 ' + brCount + ' 个 <br> 标签。', '公众号处理 SVG 时会删除这些 <br>，SVG 结构或文本布局会改变。', '移除 SVG 内的 <br>，用 SVG 的 text/tspan 元素表达换行。', svg);
    }
    var beginRegex = /\bbegin\s*=\s*(["'])(.*?)\1/gi;
    var beginMatch;
    while ((beginMatch = beginRegex.exec(svg)) !== null) {
      var value = beginMatch[2].trim();
      if (/(^|;|\s)[A-Za-z_][\w:.-]*\.click(?:[+\-]\d+(?:\.\d+)?s)?(?:;|$)/.test(value)) {
        addDiagnostic('WX-SVG-002', 'error', '检测到跨元素 SVG 动画触发器 begin="' + value + '"。', '触发器依赖 id，而公众号会剥离 SVG 的 id 属性，动画将无法启动。', '改为当前元素自触发的 begin="click"，并移除跨元素 id 依赖。', beginMatch[0]);
      }
    }
  }
}

function scanImageRules(html) {
  var imgRegex = /<img\b[^>]*>/gi;
  var match;
  while ((match = imgRegex.exec(html)) !== null) {
    var image = match[0];
    if (!/\balt\s*=/.test(image)) {
      auditLog.imageIssues.push('图片缺少 alt 文本');
      addDiagnostic('WX-IMG-001', 'warning', '图片缺少 alt 文本。', '图片加载失败或需要辅助阅读时，没有可替代的说明文字。', '为 img 添加描述图片内容的 alt 属性；装饰图可使用 alt=""。', image);
    }
    var styleMatch = /\bstyle\s*=\s*(["'])(.*?)\1/i.exec(image);
    var style = styleMatch ? styleMatch[2].toLowerCase() : '';
    var responsive = /max-width\s*:\s*100%/.test(style) && /height\s*:\s*auto/.test(style) && /display\s*:\s*block/.test(style);
    if (!responsive) {
      auditLog.imageIssues.push('图片缺少响应式样式');
      addDiagnostic('WX-IMG-002', 'warning', '图片缺少 max-width:100%; height:auto; display:block; 响应式样式。', '在不同屏幕宽度下，图片可能溢出、变形或产生基线空隙。', '在 style 中添加 max-width:100%; height:auto; display:block;。', image);
    }
    if (/\b(?:width|height)\s*=/.test(image) || /(?:^|;)\s*(?:width|height)\s*:/.test(style)) {
      auditLog.imageIssues.push('图片使用固定尺寸');
      addDiagnostic('WX-IMG-003', 'warning', '图片使用固定尺寸。', '固定尺寸在窄屏设备上可能溢出或导致比例失真。', '保留 max-width:100% 和 height:auto，避免依赖固定宽高。', image);
    }
  }
}

// ==========================================
// 5.【已证实】核心过滤函数（与 filter.js 逐字节核对一致）
// ==========================================

/**
 * 微信官方 filterBr 的 Node.js 字符串/环境兼容版
 * 记录 SVG 内部 br 被删除的数量
 */
function filterBr(html) {
  let cleaned = html;

  // A. 连续 br 过滤
  if (/(<br[^<>]*>\s*<br[^<>]*>){10,}/.test(cleaned)) {
    cleaned = cleaned.replace(/(<br[^<>]*>\s*<br[^<>]*>){10,}/g, "$1");
  }

  // B. 苹果粘贴换行过滤
  cleaned = cleaned.replace(/<br class="Apple-interchange-newline">/g, "");

  // C. SVG 内 br 的检测与剥离（使用正则模拟后端或 DOM 解析）
  // 微信官方会对 SVG Node 进行 getElementsByTagName("br") 强制移除。
  const svgBlockPattern = /<svg[^>]*>([\s\S]*?)<\/svg>/gi;
  cleaned = cleaned.replace(svgBlockPattern, function(match, innerContent) {
    auditLog.hasSvg = true;
    const brCount = (innerContent.match(/<br[^>]*>/gi) || []).length;
    if (brCount > 0) {
      auditLog.removedSvgBrs += brCount;
      return match.replace(/<br[^>]*>/gi, ""); // 清理掉 SVG 块内的 br
    }
    return match;
  });

  return cleaned;
}

/**
 * 微信官方 formatRedundancyStr 方法
 */
function formatRedundancyStr(html) {
  var targetTags = ["noscript", "iframe"];
  for (var i = 0; i < targetTags.length; i++) {
    var patternStr = "(<#targetName#\\s*[^<>]*?>)[^<\\/]+?<\\/#targetName#>".replace(/#targetName#/g, targetTags[i]);
    var replaceStr = "$1</#targetName#>".replace(/#targetName#/g, targetTags[i]);
    var regex = new RegExp(patternStr, "g");
    html = html.replace(regex, replaceStr);
  }
  return html;
}

/**
 * 微信官方 formatStyle 方法
 */
function formatStyle(html) {
  var stylePattern = '(<[^<>]*?)\\sstyle=(?:(?:"([^"]*?)")|(?:\'([^\']*?)\')|([^\'"\\s=<>]*?))([\\s\\/>])';
  var regex = new RegExp(stylePattern, "g");

  html = html.replace(regex, function(match, prefix, doubleQuoted, singleQuoted, unquoted, suffix) {
    var styleVal = doubleQuoted || singleQuoted || unquoted || "";
    if (styleVal) {
      styleVal = styleVal.replace(/&quot;/g, '"');
      var styles = styleVal.split(";");
      var keptStyles = [];
      for (var i = 0; i < styles.length; i++) {
        var stylePart = styles[i].replace(/^\s+/, "").replace(/\s+$/, "").replace(/"/g, "&quot;");
        if (stylePart) {
          keptStyles.push(stylePart);
        }
      }
      return prefix + ' style="' + keptStyles.join(";") + ';"' + suffix || "";
    } else {
      return match;
    }
  });

  return html;
}

/**
 * 微信官方 filterStyleAttr 的字符串兼容实现版（原名 filterStyleString，
 * 现改为与源码一致的函数名，filterStyleString 作为别名保留）。
 * 这是一个通用的“从 style 属性中删除指定 CSS 属性”的工具函数，源码中唯一被证实的
 * 调用点是 filterStyleAttr(html, ["background-image"])（用于粘贴图片后清理），
 * 并不存在内置的 position/z-index 黑名单——具体要过滤哪些属性由调用方决定。
 */
function filterStyleAttr(html, cssAttrList) {
  var stylePattern = '(<[^<>]*?\\sstyle=")([^"]*?)(")';
  var regex = new RegExp(stylePattern, "g");
  return html.replace(regex, function(match, prefix, styleVal, suffix) {
    var T = "(^|;|\\b)[^;]*#attr#\\s*:[^;]*[$;]";
    var cssAttrs = Array.isArray(cssAttrList) ? cssAttrList : [cssAttrList];
    var newStyleVal = styleVal;

    for (var i = 0; i < cssAttrs.length; i++) {
      var itemReg = new RegExp(T.replace("#attr#", cssAttrs[i]), "g");
      newStyleVal = newStyleVal.replace(itemReg, "$1");
    }
    return prefix + newStyleVal + suffix;
  });
}
// 向后兼容别名
var filterStyleString = filterStyleAttr;

/**
 * 微信官方 removeAttribute 方法（函数本身真实存在，但静态分析未在保存管线中找到
 * removeAttribute(html, [["*","id"], ["*","data-..."]]) 这种调用证据，因此不再在
 * runCheck 里默认拿它去剥离 id / data-*，仅保留函数供需要按标签+属性名删除属性时使用）
 */
function removeAttribute(html, tagAttrList) {
  var basePattern = '(<#tagName#[^<>]*?)\\s#attribute#=(?:(?:"([^"]*?)")|(?:\'([^\']*?)\')|([^\'"\\s=<>]*?))([\\s\\/>])';
  var replacement = "$1$5";

  for (var i = 0; i < tagAttrList.length; i++) {
    var item = tagAttrList[i];
    var tagName = item[0];
    var attrName = item[1];

    var patternStr = "";
    if (tagName === "*") {
      patternStr = basePattern.replace("#tagName#", "");
    } else {
      patternStr = basePattern.replace("#tagName#", tagName);
    }

    var regex = new RegExp(patternStr.replace("#attribute#", attrName), "g");
    while (regex.test(html)) {
      html = html.replace(regex, replacement);
    }
  }

  return html;
}

/**
 * 微信官方 formatClass 并带审计记录版
 */
function formatClass(rules, html) {
  var whiteList = rules.whiteList || classWhiteList;
  var whiteListReg = rules.whiteListReg || classWhiteListReg;
  var blackList = rules.blackList || classBlackList;

  if (!whiteList && !whiteListReg && !blackList) {
    return html;
  }

  var classPattern = '(<[^<>]*?)\\sclass=(?:(?:"([^"]*?)")|(?:\'([^\']*?)\')|([^\'"\\s=<>]*?))([\\s\\/>])';
  var regex = new RegExp(classPattern, "g");

  var formattedHtml = html.replace(regex, function(match, prefix, doubleQuoted, singleQuoted, unquoted, suffix) {
    var classAttrValue = doubleQuoted || singleQuoted || unquoted || "";
    var classes = classAttrValue.split(" ");
    var keptClasses = [];

    for (var i = 0; i < classes.length; i++) {
      var className = classes[i];
      if (className) {
        if (blackList && blackList.indexOf(className) !== -1) {
          auditLog.removedClasses.push(className + " (黑名单)");
          addDiagnostic('WX-ATTR-002', 'warning', '自定义 class "' + className + '" 不在公众号编辑器白名单内。', '该 class 会被清理，依赖它的样式或脚本选择器会失效。', '将必要的受支持样式直接写入 style 属性，不要依赖自定义 class。', match[0]);
          continue;
        } else if (whiteList && whiteList.indexOf(className) !== -1) {
          keptClasses.push(className);
          auditLog.keptClasses.push(className);
        } else if (whiteListReg && whiteListReg.length > 0) {
          var matchedReg = false;
          for (var j = 0; j < whiteListReg.length; j++) {
            var reg = whiteListReg[j];
            if (reg instanceof RegExp ? reg.test(className) : new RegExp(reg).test(className)) {
              keptClasses.push(className);
              auditLog.keptClasses.push(className);
              matchedReg = true;
              break;
            }
          }
          if (!matchedReg) {
            auditLog.removedClasses.push(className);
            addDiagnostic('WX-ATTR-002', 'warning', '自定义 class "' + className + '" 不在公众号编辑器白名单内。', '该 class 会被清理，依赖它的样式或脚本选择器会失效。', '将必要的受支持样式直接写入 style 属性，不要依赖自定义 class。', match[0]);
          }
        } else {
          auditLog.removedClasses.push(className);
          addDiagnostic('WX-ATTR-002', 'warning', '自定义 class "' + className + '" 不在公众号编辑器白名单内。', '该 class 会被清理，依赖它的样式或脚本选择器会失效。', '将必要的受支持样式直接写入 style 属性，不要依赖自定义 class。', match[0]);
        }
      }
    }

    var joinedClasses = keptClasses.join(" ").trim();
    if (joinedClasses) {
      return prefix + ' class="' + joinedClasses + '"' + suffix;
    } else {
      return prefix + suffix;
    }
  });

  return formattedHtml;
}

/**
 * 微信官方 filterClass 方法
 */
function filterClass(html, S) {
  if (!S || !html) { return html; }
  var parts = S.split(" ");
  var orPattern = "";
  for (var i = 0, len = parts.length; i < len; i++) {
    if (orPattern) { orPattern += "|"; }
    orPattern += "(?:" + parts[i] + ")";
  }

  var regex = new RegExp('(<[^<>]*?)\\sclass=((?:"[^"]*' + orPattern + '[^"]*")|(?:\'[^\']*' + orPattern + '[^\']*\'))', "g");
  return html.replace(regex, function() {
    var classes = arguments[2].replace(/['"]/g, "").split(" ");
    var kept = [];
    for (var j = 0, clen = classes.length; j < clen; j++) {
      var name = classes[j];
      if (name && (" " + S + " ").indexOf(" " + name + " ") === -1) {
        kept.push(name);
      }
    }
    return arguments[1] + ' class="' + kept.join(" ") + '"';
  });
}

// ==========================================
// 6. 检查函数（明确区分“已证实规则”与“风险提示”）
// ==========================================

/**
 *【已证实规则】id 属性剥离审计
 * 真实正则：/(<\w+[^>]*)\sid="([^">]*)"([^>]*>)/g（仅处理双引号 id）
 */
function auditIdStripping(html, tagWhiteList) {
  var whiteList = (tagWhiteList || idStripTagWhiteList).map(function(t) { return t.toLowerCase(); });
  var regex = /(<(\w+)[^>]*)\sid="([^">]*)"([^>]*>)/g;
  var match;
  var found = [];
  while ((match = regex.exec(html)) !== null) {
    var tagName = match[2].toLowerCase();
    var idValue = match[3];
    if (whiteList.indexOf(tagName) !== -1) { continue; }
    found.push({ tag: tagName, id: idValue });
    auditLog.removedIdAttributes.push('<' + tagName + ' id="' + idValue + '">');
    addDiagnostic('WX-ATTR-001', 'warning', 'id 属性会在公众号编辑器处理时被剥离。', '依赖该 id 的 CSS、锚点或 SVG 动画触发器会失效。', '不要依赖正文 HTML 的 id；SVG 动画请使用不依赖外部 id 的触发方式。', match[0]);
  }
  return found;
}

/**
 *【未证实规则 / 风险提示】行内定位类样式扫描。
 * 源码里 filterStyleAttr 唯一被证实的调用只处理 background-image（粘贴插图场景），
 * 没有找到 position/z-index/top/left/float 的过滤调用证据。这里只做“风险提示”，
 * 不再断言这些样式“一定会被删除”，请结合实际粘贴测试判断是否需要规避。
 */
const RISKY_STYLE_PROPS = ["position", "z-index", "top", "left", "float"];
function scanRiskyInlineStyles(html) {
  var stylePattern = /<[^<>]*?\sstyle="([^"]*?)"[^<>]*>/g;
  var match;
  var hints = [];
  while ((match = stylePattern.exec(html)) !== null) {
    var styleVal = match[1];
    styleVal.split(';').forEach(function(declaration) {
      var pair = declaration.split(':');
      var prop = (pair.shift() || '').trim().toLowerCase();
      var value = pair.join(':').trim().toLowerCase();
      if (!prop) { return; }
      var isRisk =
        (prop === 'position' && ['absolute', 'fixed', 'sticky'].indexOf(value) !== -1) ||
        ['z-index', 'top', 'left', 'float'].indexOf(prop) !== -1 ||
        (prop === 'display' && value === 'grid') ||
        prop.indexOf('grid-') === 0 ||
        prop === 'transform';
      if (isRisk) {
        hints.push(prop);
        auditLog.riskStyleHints.push(prop + ':' + value + ' in "' + styleVal.trim() + '"');
        addDiagnostic(
          prop === 'position' ? 'WX-CSS-001' : (prop === 'transform' ? 'WX-CSS-004' : ((prop === 'display' || prop.indexOf('grid-') === 0) ? 'WX-CSS-003' : 'WX-CSS-002')),
          'warning',
          '检测到 ' + prop + ':' + value + '，该样式在公众号正文中兼容性不稳定。',
          '不同客户端可能改变布局、层叠或变形结果。',
          '使用普通文档流、margin/padding 和 text-align 完成布局。'
        );
      }
    });
  }
  return hints;
}

/**
 *【已证实规则】Word 粘贴嵌套深度限制（clear_dom.js）
 * 节点深度或连续同类子节点达到 20 时触发扁平化。
 * 用通用标签栈扫描器估算 HTML 最大嵌套深度（忽略 void 元素/自闭合标签，且不把
 * SVG 内部图形标签计入 HTML 层级嵌套，因为 SVG 有自己的一套渲染规则）。
 * 这是对真实 DOM 深度的近似估算，可能与浏览器解析结果有细微差异，但足以发现
 * “层级过深”的排版问题。
 */
const VOID_TAGS = ["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"];
const NEST_LIMIT = 20;
const NEST_SAFE = NEST_LIMIT - 2;

function checkNestingDepth(html) {
  var tagRegex = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?(\/)?>/g;
  var depth = 0;
  var maxDepth = 0;
  var match;
  while ((match = tagRegex.exec(html)) !== null) {
    var closing = match[1] === "/";
    var tagName = match[2].toLowerCase();
    var selfClosing = !!match[3];

    if (tagName === "svg") {
      if (!closing && !selfClosing) {
        var svgEndIdx = html.indexOf("</svg>", tagRegex.lastIndex);
        if (svgEndIdx !== -1) {
          tagRegex.lastIndex = svgEndIdx + 6;
        }
      }
      continue;
    }

    if (VOID_TAGS.indexOf(tagName) !== -1 || selfClosing) {
      continue;
    }

    if (closing) {
      depth = Math.max(0, depth - 1);
    } else {
      depth++;
      if (depth > maxDepth) { maxDepth = depth; }
    }
  }
  auditLog.maxNestingDepth = maxDepth;
  auditLog.willFlattenNesting = maxDepth >= NEST_LIMIT;
  return maxDepth;
}

/**
 *【已证实规则】SVG 序列化长度限制
 * 真实位置：template_edit_fe.50ac39cd.js.下载 ~490704
 * 单个 SVG 的 outerHTML 序列化长度 >= 11000 字符时会被整体替换为 <embed>，
 * 意味着交互 SVG 的代码体积必须严格控制在该阈值以内，否则动效整体失效。
 */
const SVG_LENGTH_LIMIT = 11000;
function checkSvgSerializedLength(html) {
  var svgBlockPattern = /<svg[^>]*>[\s\S]*?<\/svg>/gi;
  var match;
  var oversized = [];
  while ((match = svgBlockPattern.exec(html)) !== null) {
    auditLog.hasSvg = true;
    if (match[0].length >= SVG_LENGTH_LIMIT) {
      oversized.push(match[0].length);
      auditLog.oversizedSvgBlocks.push(match[0].length);
      addDiagnostic('WX-SVG-003', 'error', 'SVG 序列化长度为 ' + match[0].length + ' 字符，达到 11000 字符硬性阈值。', '该 SVG 会被公众号替换为 <embed>，图形和动效都无法按原样保留。', '删除冗余属性和路径，拆分或简化 SVG，使单个 SVG 小于 11000 字符。', match[0]);
    }
  }
  return oversized;
}

/**
 *【弱提示，非确定规则】疑似冗余空节点扫描。
 * 真实的 deleteRedundantNode 触发条件复杂得多：父节点子元素数 > 20 且连续 15+ 个
 * 空子节点才会触发清理；豁免标签（已证实）为
 * img|hr|svg|mp-common|iframe|cps|br|a|mp|video|audio|path|embed，
 * 或 style 中含 background-image 也豁免。
 * 这里只做单节点级别的启发式提示（不复现 >20 子节点/连续 15+ 的真实阈值判断），
 * 命中不代表一定会被清理，仅供人工复核排版结构是否有明显冗余的空标签。
 */
const EMPTY_NODE_EXEMPT_TAGS = /^(img|hr|svg|mp-common|iframe|cps|br|a|mp|video|audio|path|embed|rect|circle|ellipse|line|polyline|polygon|g|defs|use|text|tspan|animate|set)/i;
function scanEmptyNodeSuspects(html) {
  var tagPattern = /<([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*)>\s*<\/\1>/g;
  var match;
  var suspects = [];
  while ((match = tagPattern.exec(html)) !== null) {
    var tagName = match[1];
    var attrs = match[2] || "";
    if (EMPTY_NODE_EXEMPT_TAGS.test(tagName)) { continue; }
    if (/background-image/.test(attrs)) { continue; }
    suspects.push(match[0]);
    auditLog.emptyNodeSuspects.push(match[0].slice(0, 80));
  }
  return suspects;
}

// ==========================================
// 7. Node.js 命令行入口及检查流程
// ==========================================

function resolveFilePath(filePath) {
  if (fs.existsSync(filePath)) {
    return filePath;
  }

  try {
    const dir = path.dirname(filePath);
    const base = path.basename(filePath);
    if (fs.existsSync(dir)) {
      const files = fs.readdirSync(dir);
      const normalize = (str) => str.replace(/["'“”‘’]/g, '');
      const normalizedBase = normalize(base);

      const matchedFile = files.find(f => normalize(f) === normalizedBase);
      if (matchedFile) {
        const resolvedPath = path.join(dir, matchedFile);
        console.log(`\x1b[33m[提示] 检测到文件名引号可能被终端剥离，已自动匹配到文件: ${matchedFile}\x1b[0m`);
        return resolvedPath;
      }
    }
  } catch (err) {
    // Ignore error
  }

  return filePath;
}

function runCheck(filePath) {
  const resolvedPath = resolveFilePath(filePath);
  if (!fs.existsSync(resolvedPath)) {
    console.error(`\x1b[31m[错误] 目标文件不存在: ${filePath}\x1b[0m`);
    process.exit(1);
  }
  filePath = resolvedPath;

  const fileContent = fs.readFileSync(filePath, 'utf8');
  resetAuditLog();

  console.log(`\n\x1b[36m==================================================`);
  console.log(`🔍 微信公众号排版规范校验工具 - 开始分析`);
  console.log(`文件: ${path.basename(filePath)}`);
  console.log(`==================================================\x1b[0m`);

  // 执行全套清洗/审计逻辑
  let output = fileContent;
  scanBannedTags(fileContent);
  scanConsecutiveBrs(fileContent);
  scanRiskyInlineStyles(fileContent);
  scanImageRules(fileContent);
  output = filterBr(output);
  output = formatStyle(output);
  formatClass({
    whiteList: classWhiteList,
    whiteListReg: classWhiteListReg,
    blackList: classBlackList
  }, output);
  auditIdStripping(output);
  scanSvgAnimationRules(fileContent);
  checkNestingDepth(output);
  checkSvgSerializedLength(fileContent);
  scanEmptyNodeSuspects(output);

  let hasWarning = auditLog.diagnostics.some(function(item) { return item.severity === 'warning'; });
  let hasError = auditLog.diagnostics.some(function(item) { return item.severity === 'error'; });

  console.log(`\n\x1b[35m[已证实 1/6] class 白名单过滤审计:\x1b[0m`);
  const uniqueRemovedClasses = [...new Set(auditLog.removedClasses)];
  if (uniqueRemovedClasses.length > 0) {
    console.log(`⚠️  注意: 以下自定义类名将被剔除（不在微信白名单内）:`);
    console.log(`   ${uniqueRemovedClasses.join(', ')}`);
    console.log(`   💡 提示: 请确保没有依赖自定义 class 修饰排版，必须全部使用行内 style。`);
    hasWarning = true;
  } else {
    console.log(`✅ 所有类名均在微信官方白名单内，或无类名修饰。`);
  }

  console.log(`\n\x1b[35m[已证实 2/6] id 属性剥离审计:\x1b[0m`);
  if (auditLog.removedIdAttributes.length > 0) {
    console.log(`\x1b[33m⚠️  警告: 检测到将被剥离的 id 属性共 ${auditLog.removedIdAttributes.length} 处。`);
    console.log(`   这会导致基于 ID 的跨元素 SVG 动画 (如 begin="btn.click") 彻底失效！`);
    console.log(`   细节: ${auditLog.removedIdAttributes.slice(0, 5).join(', ')} ...\x1b[0m`);
    hasWarning = true;
  } else {
    console.log(`✅ 未检测到会被剥离的 id 属性。`);
  }

  console.log(`\n\x1b[35m[已证实 3/6] Word 粘贴嵌套深度审计（限制 20 层，安全线 18 层）:\x1b[0m`);
  if (auditLog.willFlattenNesting) {
    console.log(`\x1b[31m❌ 错误: 检测到最大嵌套深度达到 ${auditLog.maxNestingDepth} 层，已到达/超过微信 Word 粘贴 20 层扁平化阈值。`);
    console.log(`   从 Word 粘贴时这部分结构会被强制扁平化处理，排版可能整体错乱！\x1b[0m`);
    hasError = true;
  } else if (auditLog.maxNestingDepth > NEST_SAFE) {
    console.log(`\x1b[33m⚠️  警告: 检测到最大嵌套深度为 ${auditLog.maxNestingDepth} 层，已超过建议安全线（${NEST_SAFE} 层）。`);
    console.log(`   虽然还没到 20 层扁平化阈值，但建议精简结构以留出余量。\x1b[0m`);
    hasWarning = true;
  } else {
    console.log(`✅ 最大嵌套深度为 ${auditLog.maxNestingDepth} 层，在安全范围内。`);
  }

  console.log(`\n\x1b[35m[已证实 4/6] SVG 序列化长度审计（单个 SVG >= 11000 字符会被替换为 <embed>）:\x1b[0m`);
  if (auditLog.oversizedSvgBlocks.length > 0) {
    console.log(`\x1b[31m❌ 错误: 检测到 ${auditLog.oversizedSvgBlocks.length} 个 SVG 块的序列化长度超过 11000 字符（${auditLog.oversizedSvgBlocks.join(', ')}）。`);
    console.log(`   保存后这些 SVG 会被整体替换为 <embed>，交互动效将彻底失效，请精简 SVG 代码体积！\x1b[0m`);
    hasError = true;
  } else if (auditLog.hasSvg) {
    console.log(`✅ 检测到 SVG 元素，序列化长度均在 11000 字符以内。`);
  } else {
    console.log(`ℹ️  未包含 SVG 元素。`);
  }

  console.log(`\n\x1b[35m[已证实 5/6] SVG 内部 <br> 审计:\x1b[0m`);
  if (auditLog.removedSvgBrs > 0) {
    console.log(`\x1b[31m❌ 错误: 检测到 SVG 块内部包含了 ${auditLog.removedSvgBrs} 个 <br> 标签。`);
    console.log(`   微信会在解析时直接删除这些 <br>。请避免在 SVG 块内使用 <br> 进行软换行！\x1b[0m`);
    hasError = true;
  } else {
    console.log(`✅ SVG 块内部未发现非法 <br> 换行符。`);
  }

  console.log(`\n\x1b[35m[已证实 6/6] 疑似冗余空节点扫描（弱提示，真实触发条件更复杂，见代码注释):\x1b[0m`);
  if (auditLog.emptyNodeSuspects.length > 0) {
    console.log(`ℹ️  提示: 发现 ${auditLog.emptyNodeSuspects.length} 处疑似空标签（非豁免标签、且无 background-image）:`);
    console.log(`   ${auditLog.emptyNodeSuspects.slice(0, 5).join(' | ')} ...`);
    console.log(`   这不一定会被微信清理（真实阈值是父节点 >20 子节点且连续 15+ 空子节点），但建议人工确认是否为无意义空标签。`);
  } else {
    console.log(`✅ 未发现明显的冗余空标签。`);
  }

  console.log(`\n\x1b[33m[未证实规则 / 风险提示] 定位类样式使用扫描（position/z-index/top/left/float):\x1b[0m`);
  if (auditLog.riskStyleHints.length > 0) {
    const uniqueHints = [...new Set(auditLog.riskStyleHints.map(h => h.split(' in ')[0]))];
    console.log(`ℹ️  提示: 检测到使用了 ${uniqueHints.join(', ')} 等定位/浮动样式。`);
    console.log(`   目前没有在微信源码中找到这些样式一定会被过滤的调用证据，仅供参考，不计入下方通过/失败结论。`);
  } else {
    console.log(`✅ 未检测到 position: absolute 等定位样式使用。`);
  }

  console.log(`\n\x1b[35m[详细诊断] 禁用标签、SVG 动画、图片与换行规则:\x1b[0m`);
  if (auditLog.diagnostics.length > 0) {
    auditLog.diagnostics.forEach(function(item) {
      var label = item.severity === 'error' ? '错误' : (item.severity === 'warning' ? '风险' : '提示');
      console.log(`  [${item.code}] ${label}: ${item.message}`);
      console.log(`    后果: ${item.consequence}`);
      console.log(`    建议: ${item.suggestion}`);
    });
  } else {
    console.log(`✅ 未命中新增兼容性规则。`);
  }

  console.log(`\n\x1b[36m==================================================`);
  console.log(`🏁 校验结束总结:`);
  if (hasError) {
    console.log(`\x1b[31m❌ 存在已证实规则下的严重错误！文章上传微信后大概率出现排版渲染崩溃，请立即根据提示修正代码。`);
    console.log(`==================================================\x1b[0m`);
    process.exit(1);
  } else if (hasWarning) {
    console.log(`\x1b[33m⚠️  存在潜在警告！部分交互或类名/属性在微信里可能会失效。`);
    console.log(`   请确保这在你的设计意图之内。\x1b[0m`);
    console.log(`==================================================\x1b[0m`);
    process.exit(0);
  } else {
    console.log(`\x1b[32m✅ 已证实规则均通过！在此基础上未发现明显的兼容性冲突。`);
    console.log(`==================================================\x1b[0m`);
    process.exit(0);
  }
}

// 如果是 Node.js 命令行直接调用
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.log("用法: node wechat_format_rules_source.js <html_file_path>");
    process.exit(1);
  }
  runCheck(args[0]);
}

// 导出模块方法以防需要被作为 commonjs 引用
module.exports = {
  // 配置
  classWhiteList,
  classWhiteListReg,
  classBlackList,
  idStripTagWhiteList,
  PASTE_MATCH_STYLE_WHITELIST_REF,
  WORD_PASTE_FLATTEN_STYLE_WHITELIST_REF,
  // 已证实核心过滤函数
  formatClass,
  formatStyle,
  filterStyleAttr,
  filterStyleString,
  removeAttribute,
  filterBr,
  formatRedundancyStr,
  filterClass,
  // 检查函数
  auditIdStripping,
  scanBannedTags,
  scanConsecutiveBrs,
  scanRiskyInlineStyles,
  scanSvgAnimationRules,
  scanImageRules,
  checkNestingDepth,
  checkSvgSerializedLength,
  scanEmptyNodeSuspects,
  resetAuditLog,
  get auditLog() { return auditLog; }
};
