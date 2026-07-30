---
mode: agent
---
Define the task to achieve, including specific requirements, constraints, and success criteria.

# 微信公众号文章排版生成规范（修订版）

## 任务定义
当用户要求生成微信公众号文章 HTML 排版时，必须在不改变原文信息的前提下，输出可直接粘贴到公众号编辑器的兼容代码。

## 成功标准
- 输出完整 HTML 文档：包含 `html`、`head`、`body`。
- 所有样式均为内联样式，仅使用 `style` 属性。
- 不包含微信会过滤或高风险失效的实现（见“禁用项”）。
- 保留原文结构、标点与语义，不增删事实内容。
- 在安卓和 iOS 微信中具备可读性与基本一致性。

## 一、基础技术要求与底层限制

### HTML 结构与微信底层映射机制
> 以下标注【已证实】的规则，均已通过对微信编辑器前端资源包（旧版 UEditor 管线 `template_edit_fe.e4e63001.js.下载`、`editor_filter.js`、灰度 ProseMirror 编辑器管线 `appmsg_edit_v2_gray_fe.704669e7.js.下载` 等）的静态逆向核实到具体函数/正则/调用点；标注【经验建议】的规则没有找到直接源码证据，作为工程上规避不确定性的最佳实践保留，不代表微信一定会这样处理。

- **块级标签处理【经验建议，非强制转换】**：没有找到微信把 `div`/`article`/`script`/`style`/`link` **全局强制转换为 `section`** 的证据。真实机制是按标签名分支处理的，例如：`div` 会被拆成 `<p>` 子节点后删除自身；`style`/`script` 的内容会被编码后存进 `cdata_data` 属性、标签本身改写为空 `div`；`dl`→`ul`、`dt`/`dd`→`li`。由于这类改写细节不完全可控，**仍建议优先使用 `section` 作为核心块级标签**，规避未知的标签重写风险，但不要再把"强制转 section"当作确定事实来做其他推断。
- **Word 粘贴嵌套深度限制【已证实】**：`clear_dom.js` 对 Word 粘贴内容设置 `deepLen:20` 与 `flatLen:20`。当符合其节点条件的嵌套深度或连续同类子节点数达到 **20** 时，会执行扁平化清理（Flatten DOM）。这不是草稿 API 同步的通用改写规则；生成排版仍建议控制在 **18 层以内**，为人工复制、从 Word 粘贴和后续编辑预留余量。`wechat_format_rules_source.js` 的 `checkNestingDepth()` 会在 >=20 层时报错。
- **空标签清理【已证实存在，但触发条件比想象中更苛刻】**：真实的 `deleteRedundantNode` 触发条件是"父节点子元素数 > 20 且连续 15+ 个空子节点"才会清理，不是任意一个空标签都会被删。豁免的标签集合（已证实）为 `img|hr|svg|mp-common|iframe|cps|br|a|mp|video|audio|path|embed`，或 `style` 中含 `background-image` 也豁免。生成排版时仍应避免堆砌无意义的空标签，但不必对单个空 `<p></p>` 过度紧张。
- **连续换行符【已证实】**：连续的 `<br>` 达到 10 个（即 `(<br>\s*<br>){10,}`）会被压缩为 1 组，生成排版时不应依赖大量连续 `<br>` 做空白间隔。
- **SVG 序列化长度限制【已证实，新发现的硬指标】**：单个 `<svg>...</svg>` 的序列化（`outerHTML`）长度达到 **11000 字符**时会被整体替换为 `<embed>`，导致该 SVG 的交互动效彻底失效。制作 SVG 交互卡片时必须把单块 SVG 代码体积严格控制在 11000 字符以内（`wechat_format_rules_source.js` 的 `checkSvgSerializedLength()` 会检查此项）。

### 标准段落结构
- 使用 `section` 包裹 `p`，并保持统一段距与缩进。
- 标准结构如下：
  ```html
  <section style="margin:20px [左右间距] 0 [左右间距];">
    <p style="margin:0 [左右间距]; font-size:15px; color:rgb(0, 0, 0); letter-spacing:1px; line-height:2em; text-indent:2em; max-width:100%;">
      <span style="letter-spacing:1px;">文字</span>
    </p>
  </section>
  ```
- `[左右间距]` 只能在 `3px`、`4px`、`5px` 中选择一个，全文必须统一。

### 文本与标点规范
- 正文样式统一：`font-size:15px; line-height:2em; letter-spacing:1px; color:rgb(0, 0, 0);`。
- 使用中文标点：，。；！？：（）
- 引号统一转义：双引号使用 `&ldquo;` 与 `&rdquo;`，单引号使用 `&lsquo;` 与 `&rsquo;`。
- 注意省略号不转义，直接使用`...`。

### 图片规范
- 图片应使用用户提供或已确认有权使用的地址；未提供图片时，不要插入占位图。
- 必须包含 `alt` 描述。
- 常规图片统一设置：`max-width:100%; height:auto; display:block;`。
- 如出现图片间白缝，可允许微调 `margin-top:-1px;`。

## 二、视觉设计规范

### 色彩系统
- 主色 1-2 种，辅助色最多 1 种。
- 正文色：`#000000`；次要文字：`#666666`。
- 强调色建议低饱和，重点不超过 3 处。

### 排版细节
- 标题、引言等居中内容显式设置 `text-align:center;`。
- `font-weight:bold;` 仅用于核心信息，整体占比不超过 10%。
- 区块分隔优先用 `padding:10px 0;` 或浅灰背景。
- 若原始 Markdown 有加粗内容，最终排版必须保留加粗语义。
- 少用引用条。

## 三、SVG 与动效规范

### 可用能力
- 仅允许 SVG 原生 SMIL 动画：`animate`、`animateTransform`、`set`。
- 可用动画属性：不透明度（opacity）、显示隐藏（visibility）、位移、缩放、旋转等。
- 推荐使用 `viewBox` 进行自适应布局，宽度建议 `width="100%"`，并控制 SVG 文件体积。

### ⚠️ SVG 交互的核心限制（微信公众号平台）

微信公众号编辑器在保存草稿时，会通过 `getEditorData` 里的独立正则**剥离元素上的 `id` 属性**（存在插件标签白名单例外，具体见"属性过滤规则"一节），效果上等同于"HTML/SVG 元素上的 `id` 基本不可依赖"。

1. **禁用跨元素 ID 触发**：任何形如 `begin="elementId.click"` 依赖外部 `id` 定位触发源的动效方案，在粘贴并保存后，均会因为 `id` 的缺失而失效。
2. **禁止多源触发**：形如 `begin="id1.click;id2.click"` 的多源触发也无法在微信中支持。

### SVG 交互推荐设计模式（无 ID 自触发方案）

为了保证在没有 `id` 属性的微信环境下依然能够正常工作，所有点击交互设计必须采用**无 ID 依赖的自触发模式**。即利用 `begin="click"` 监听被触发元素自身（或其直接包裹的父级 `<g>` 容器）的点击事件。

以下是几种经典的无 ID 自触发交互实现模式：

#### 模式一：单节点自状态切换（例如“点击排雷”勾选变色）

适用于“点击某按钮/某组件后，该组件自身发生颜色、文字或形态变化”的自包含状态交互。
**实现原理**：在同一个 `<g>` 容器中，叠加放置“初始状态”与“触发后状态”元素。“触发后状态”默认置于上方并隐藏（如 `opacity="0"` 或 `visibility="hidden"`）。点击该 `<g>` 容器时，利用自触发 `<set>` 将其状态修改为显示，覆盖在初始状态之上。

```xml
<svg viewBox="0 0 100 40" style="width: 100px; height: 40px; cursor: pointer;">
  <!-- 初始状态：未排雷（红色） -->
  <rect width="100" height="40" rx="6" fill="#d94b36" />
  <text x="50" y="25" fill="#ffffff" text-anchor="middle" font-size="14">未排</text>
  
  <!-- 触发后状态：已排雷（绿色，默认隐藏，点击后显现并覆盖初始状态） -->
  <g opacity="0">
    <rect width="100" height="40" rx="6" fill="#2ecc71" />
    <text x="50" y="25" fill="#ffffff" text-anchor="middle" font-size="14">已排</text>
    <!-- 点击父级容器 <g> 自身触发显示，无需任何外部 ID -->
    <set attributeName="opacity" to="1" begin="click" fill="freeze" />
  </g>
</svg>
```

#### 模式二：多层堆叠 + 自消除（“遮罩盖帽法”压顶与揭秘）

适用于“层层揭开、展示后续剧情或揭晓历史真相”的单向线性顺序交互。
**实现原理**：SVG 中后写的元素会覆盖在先写元素上方。我们将最终展示的内容（如“真相答案”）写在最底层，将遮罩蒙版（如“点击揭秘”）写在最顶层。点击遮罩所在的 `<g>` 容器时，触发自身的隐藏动画，使自身消失，从而露出底层的真实内容。

```xml
<svg width="100%" viewBox="0 0 600 400">
  <!-- 底层：最终展示内容（始终存在） -->
  <g>
    <rect width="600" height="400" fill="#FFE0B2" />
    <text x="300" y="200" text-anchor="middle" font-size="20">这是最终的历史真相内容</text>
  </g>

  <!-- 顶层：点击遮罩（点击自身消失，露出底层） -->
  <g style="cursor: pointer;">
    <rect width="600" height="400" fill="#BBDEFB" />
    <text x="300" y="200" text-anchor="middle" font-size="20">点击揭晓真相</text>
    <!-- 点击自身后隐藏，露出被它盖在下面的底层元素 -->
    <set attributeName="visibility" to="hidden" begin="click" fill="freeze" />
  </g>
</svg>
```

#### 局限与注意事项

1. **动画指令的放置**：所有的动画指令（`<set>` / `<animate>` / `<animateTransform>`）必须直接写在需要发生属性改变的元素（或其父容器）内部，严禁使用 `begin="other.click"` 跨层控制。
2. **点击触发与事件监听**：在微信环境中，最广泛兼容的点击监听是 `begin="click"`，它只监听其直接父级元素的点击事件，无需任何 ID。
3. **透明热区设计**：若仅希望元素的某一部分区域响应点击（如特定局部按钮），可在该容器 `<g>` 内放置一个 `fill-opacity="0"` 的透明 `<rect>`，并将 `<set>` 或 `<animate>` 依然写在需要改变状态的 `<g>` 容器上。
4. **状态路径单向化**：由于微信不支持复杂的条件逻辑，所有的交互应设计为单向且直接的（例如点击后仅有一次性的显示、隐藏或平移动作），避免多路往复逻辑导致编辑器保存兼容性崩溃。

## 四、底层兼容性与过滤规则（核心难点）

### 行内样式使用建议（原"极严 CSS 样式过滤"，已修正）
- **重要修正**：此前"行内标签只保留 7 个 CSS 样式属性"的说法**没有找到通用保存态强制过滤的源码证据**，是历史文档的推测性描述，已确认存在偏差，特此修正。静态逆向实际找到的是两份**用途完全不同、都不是通用保存过滤规则**的样式属性名单：
  1. 粘贴时用户主动选择"匹配目标格式"选项才会生效的 9 项白名单：`background-color`、`color`、`font-size`、`font-family`、`line-height`（源码拼写为 `line-leight`，疑似微信自身拼写 bug）、`letter-spacing`、`font-style`、`font-weight`、`text-decoration`。这只在粘贴弹窗里用户手动选择该选项时才会生效，AI 直接生成/替换 HTML 代码的场景不会触发。
  2. 仅在"从 Word 粘贴且节点深度或连续同类子节点数 >= 20"时才触发的扁平化专用样式白名单（24 项，含 `margin`/`padding`/`border`/`display` 等，见 `wechat_format_rules_source.js` 中的 `WORD_PASTE_FLATTEN_STYLE_WHITELIST_REF`），这明确说明微信在某些场景下是保留 `margin`/`padding`/`border` 等布局样式的，与"行内标签会丢弃布局样式"的旧说法直接矛盾。
- **修正后的工程建议（经验建议，非确定规则）**：即便没有确凿的强制过滤证据，出于兼容性与可维护性考虑，仍**建议**尽量把 `padding`、`margin`、`border`、`width`、`height` 等排版/布局类样式写在块级标签（`section`、`p`、`table`、`td`）上，`span` 等行内标签主要承载 `color`/`font-size`/`font-weight`/`background-color`/`text-decoration` 等文字级样式，这是稳妥的降级策略而不是被验证的强制规则。

### 类名 (Class) 过滤规则
- 微信会调用 `formatClass` 过滤掉不合规的类名。仅允许以下类名通过：
  - 精确白名单：`rich_pages`, `blockquote_info`, `blockquote_biz`, `normal_text_link`, `weapp_text_link`, `weapp_image_link`, `code-snippet` 等。
  - 正则白名单：`/^editor__content__/`, `/^wxw/`, `/^wx-/`, `/^wx_(?!text_underline)/`, `/^js_/`, `/^cps_inner/`, `/^bizsvr_/`, `/^icon_emoji_/`, `/^custom_select_card/`。
- **因此**：所有自定义 Class 都会失效，排版样式必须全部采用内联样式。

### 属性 (Attributes) 过滤规则
- **id 属性会被剥离【已证实，但机制与此前描述不同】**：真实机制并非"ProseMirror 序列化器统一剥离"，而是旧版编辑器 `getEditorData` 里一条独立正则 `/(<\w+[^>]*)\sid="([^">]*)"([^>]*>)/g` 在保存时执行替换；该正则**存在插件标签白名单例外**（命中特定标签名时会保留 id），且只处理双引号写法的 `id`。灰度版 ProseMirror 编辑器是否重复此逻辑尚未证实。保守起见，**仍应假定 `id` 会被剥离**：任何依赖 `id` 的功能（SVG 动画跨元素触发、CSS `#id` 选择器等）都不要作为核心方案依赖。
- **`data-*` 自定义属性【未发现被批量删除的证据】**：没有找到"保存时统一删除所有 `data-` 前缀属性"的调用。实际观察到的裁剪规则是：属性名必须匹配 `/^[a-zA-Z_][a-zA-Z0-9_-]*$/`（不合法的属性名会被丢弃），且属性值长度有上限（普通属性约 2048 字符，`style` 类可放宽一倍，`data-pm-slice` 例外）。因此 `data-` 属性总体上是可以用来传递自定义参数的，但不要写超长的值，也不要用不合法字符做属性名。
- `class`（仅白名单内）与 `style` 按各自的过滤规则处理（见前后文）。

### 明确禁用项
- 禁止 `<style>`、外链样式表、`script`、`iframe`（`formatRedundancyStr` 已证实会清空 `iframe`/`noscript` 内的文本内容）。
- **经验建议**：不依赖 `position:absolute`、`position:fixed` 做核心布局（未找到会被强制过滤的证据，但也未验证一定保留，稳妥起见仍按不可靠对待）。
- 禁止使用媒体查询（`@media`）作为适配主方案（`<style>` 标签本身不被支持）。
- 禁止使用 `grid` 作为核心布局（经验建议，微信正文容器渲染环境对新特性支持不稳定）。
- **禁止在 SVG 中使用 `id` 属性进行跨元素动画触发**（`begin="elementId.click"` 会因 id 被剥离而失效，已证实）。
- **禁止使用 `begin="id.click;id2.click"` 分号多源触发**（即使 id 未被剥离，微信的 id 重写正则也无法处理分号分隔的多 ID）。
- **单个 SVG 代码体积不得达到 11000 字符**（已证实，超过会被整体替换为 `<embed>`，交互彻底失效）。

### 布局策略
- 简单结构优先流式文档流。
- 复杂结构优先 `table` 布局；使用 `table` 仅作布局容器时必须隐藏边框：
  - `table`：`border-collapse:collapse; border:none;`
  - `td`：`border:none;`
- `flex` 可谨慎用于简单场景，不作为唯一关键布局手段。

### 时间线与分栏
- 避免绝对定位和层叠定位。
- 时间线连接线优先用表格单元格边框或背景实现。
- 复杂布局优先采用 `display:table` + `display:table-cell` 代替 `flex` 布局。

### transform 使用策略
- CSS `transform` 在新版本微信中通常可用，但对于关键信息展示，不得把可读性建立在 `transform` 必然生效的前提上。

### 多端适配
- 字号默认 `15px`，行高保持 `line-height:2`。
- 可少量使用 `vw` / `vh` 做尺寸适配，但必须提供可读的兜底表现。

## 五、输出格式要求

### 必备文档结构
- 必须包含：
  - `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>`
- 样式全部写在标签 `style` 属性内。

### 内容处理原则
- 严格遵循原文结构，仅优化排版表现，不增删信息。
- 排版风格需匹配主题气质，但优先兼容与可读性。

## 六、生成后自检清单（必须执行）
- 是否存在 `<style>`、`script`、`iframe`、外链 CSS。
- 是否存在依赖 `id`/`class` 的关键样式或交互。
- **SVG 交互是否使用了 `begin="elementId.click"`**（必须改为 `begin="click"` 自触发）。
- **SVG 交互是否使用了无 ID 的自触发方案**（如遮罩盖帽法、自状态转换法，禁止依赖外部 `id`）。
- **单个 SVG 代码体积是否 >= 11000 字符**（已证实的硬性阈值，超过会被替换为 `<embed>`）。
- 整体嵌套层级是否 >= 20 层（Word 粘贴时会被扁平化，建议控制在 18 层以内）。
- 是否存在核心布局依赖 `position:absolute/fixed` 或 `grid`（经验建议规避，非已证实强制过滤）。
- 图片是否都带 `alt`，且设置了 `max-width:100%; height:auto;`。
- 全文左右边距是否只使用同一个值（3/4/5px 之一）。
- 中文标点与引号实体是否已统一。
- 若含 SVG：是否含 `viewBox`、是否控制体积（<11000 字符）、`image` 是否写宽高与可用链接。
- **静态工具校验（强制）**：每次生成或修改排版 HTML 文件后，**必须**直接在宿主机终端通过命令运行微信排版规范校验工具：
  `node wechat_format_rules_source.js <排版HTML路径>`
  必须仔细阅读控制台输出的检查报告。报告分两类：标注"已证实"的检查项若报 `❌ 错误`（如嵌套深度 >=20、SVG 超长、SVG 内含 `<br>`）**必须**修复；标注"风险提示/弱提示"的项目（如定位类样式、疑似空节点）仅供参考判断，不强制要求清零。只要不再出现 `❌ 存在已证实规则下的严重错误`，即可认为通过校验。

## 执行要求
- 当用户请求生成公众号文章 HTML 时，自动应用本规范。
- 始终使用中文沟通与说明。
- 输出结果必须可直接用于微信公众号编辑器，并尽量减少二次手工修正。
