# 源码编辑 Agent

新运行默认采用 `v2` 协议。文章以 `/article.html` 交给模型，模型自主选择读取、搜索、局部替换、多处补丁或全文重写。修改首行缩进可只替换 `text-indent`，无需回传整个段落；修改不会经过 DOM 重序列化，也不会自动压缩或格式化 HTML。

## 授权工作区

| 路径 | 权限与来源 |
| --- | --- |
| `/article.html` | 当前文章，可读写 |
| `/reference.html` | 当前会话绑定的排版参考，只读 |
| `/templates/<id>.html` | 按会话附加顺序标为 `@组件N` 的组件，只读 |
| `/theme/recipe.json` | 当前已批准提案或只读主题参考的配方与元数据 |
| `/theme/components.md`、`/theme/<id>.html` | 当前授权主题的组件资料，只读 |
| `/history/<version_id>.html` | 当前文章的可访问历史版本，只读、按需加载 |

这些是虚拟路径，不是服务器文件接口。不能访问未注册文件、其他文章的历史版本或系统路径。历史目录使用 `list_files(directory="/history")` 分页列出；读取历史直接恢复版本源码，无需建立 DOM 索引。

## 核心工具

| 工具 | 用法 |
| --- | --- |
| `list_files` | 列目录，支持 `directory`、`cursor`、`limit`；预算不足时保留完整条目并提供下一游标 |
| `read_file` | 读取全文、`start_line/end_line` 或 `start/end`；返回实际范围、revision、源码及 `next_cursor` |
| `search_files` | 字面量搜索，支持 `paths`、`case_sensitive`、`context_chars`、分页；长行只返回匹配附近源码 |
| `edit_file` | 提交同一 revision 下的多项 `old_text/new_text`；可选 `start/end`、`replace_all` |
| `apply_patch` | 提交单文件、多 hunk 的严格 unified diff，包含文件头和 hunk 行号 |
| `write_file` | 使用当前 revision 整体写入文章 |

源码预算按包含元数据的实际 JSON 计算。普通多行源码尽量保留整行；压缩长行可以按字符分页，模型不受块数量限制。行号从 **1** 开始；字符偏移从 **0** 开始，`end` 不含末位，按 Python Unicode 字符计算，中文及 emoji 不按 UTF-8 字节或 JavaScript UTF-16 单元计数。行号、范围与源码内容分别返回，不将显示行号写进源码。

读取分页时保留原请求范围，使用返回的 `revision` 和 `next_cursor`。搜索续读指定一个文件及其 revision；多文件结果分别提供游标。revision 过期会拒绝续读，避免拼接不同快照。

```json
{
  "path": "/article.html",
  "revision": "来自当前状态或读取结果",
  "edits": [{"old_text": "text-indent:0", "new_text": "text-indent:2em", "start": 120, "end": 260}]
}
```

默认匹配必须唯一；重复内容通过范围限定，或显式 `replace_all=true` 替换全部。插入使用空 `old_text` 以及相同的 `start/end`。同批修改全部基于原快照定位，原文不匹配、范围重叠、只读路径、未知占位符或 revision 冲突时整批不写入。错误返回匹配位置或冲突范围；不做模糊匹配。

补丁严格匹配指定行号的原文和上下文。保留 CRLF、原有混合换行上下文和文件末尾换行状态；新增行沿用文件换行形式。缺末尾换行使用标准 `\ No newline at end of file` 标记。跨标签、跨段落修改以及组件移动无需节点协议。

成功写入返回最新 revision 和修改范围。`changes[].start/end` 指向**写入后的源码**，`before_start/before_end` 指向调用时的快照。已读取且 revision 仍有效的源码可继续用于修改；写入后只在需要重新定位时读取，不要求固定的“地图→搜索→读块→修改”调用链。

## 图片、检查与预览

内联 data 图片显示为内容指纹生成的 `__YIBAN_INLINE_DATA_<sha256>__`，同一数据在重启及暂停恢复后保持一致。读取、搜索、选区、补丁和诊断位置全部基于这个模型可见版本；写入时恢复原始数据，未知或不完整的占位符拒绝写入。

每次写入复用现有锁、取消检查、候选验证、检查点和 SSE 预览流程，只进行一次 HTML 结构检查。结构问题以 warning 返回并保留候选，供下一次局部修改修复；已批准主题的严格验证仍可以在提交前拒绝候选。需要定位选区或查看图片时才构建 DOM 索引。

缩进、颜色等简单样式修改只做结构检查。结构调整、主题应用、用户要求或兼容性存在疑点时，最终写入可附 `check_wechat=true`，也可单独调用 `check_compliance`。浏览器检测失败不会丢弃已经完成的写入；任何文章修改都会使旧检测报告失效。

`enable_tool_groups` 按需加载 `images`、`history`、`themes` 的专用能力。源码文件读取始终开放；历史会话查询、图片查看/生成/变换和主题管理沿用已有权限。新协议会拒绝尚未加载的专用工具和旧块编辑工具。脚本执行不属于此接口。

已开启提示缓存优化的 OpenAI 兼容／Responses 模型使用工具 schema 指纹区分缓存路由。相同工具组合顺序固定，连续写入只刷新请求末尾的运行状态；新增组会改变缓存前缀，首个请求需重新建立缓存。重复加载不再绑定或减少预算。最新状态中记录已加载组，暂停恢复沿用相同组合。详见 [提示缓存优化](PROMPT_CACHE_OPTIMIZATION.md)。

前端显示源码工具名称、文件范围、独立的源码文本、续读提示和修改状态。完整调用与活动信息沿用现有审计保存；模型收到精简的写入结果。

## 兼容与回退

在后端环境中设置 `CHAT_AGENT_TOOL_PROTOCOL=v1` 可将**新运行**切回旧工具，默认值为 `v2`，重启后端生效。无需数据库迁移。

暂停任务在原有 `execution_context_json` 中保存 `tool_protocol` 和 `loaded_tool_groups`。没有协议字段的旧任务按 `v1` 恢复；已暂停的 `v2` 任务重新注册文件与稳定占位符、提供当前 revision，并拒绝基于旧版本的写入。切换默认开关不会更改已经暂停任务的协议。

## 验证与对照

`test_source_workspace.py` 和 `test_source_agent.py` 覆盖压缩 HTML、选区缩进、重复文字、多处原子修改、显式全文替换、组件移动、全文重构、参考只读、中文/emoji、CRLF、混合换行、图片占位符、诊断位置、冲突、取消、检查点、结构错误修复、工具加载、预算、缓存和暂停恢复。历史测试额外覆盖文章隔离与懒加载。

从 `backend` 目录运行：

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests
.\venv\Scripts\python.exe scripts\benchmark_source_agent.py
.\venv\Scripts\python.exe scripts\benchmark_source_agent.py --live --model-id 40 --runs 1
```

默认 benchmark 是脚本模型驱动的机制验证，不能用于证明真实延迟。`--live` 对两个协议使用相同合成文章、自然请求、模型、网关、推理设置和缓存开关，不预设模型的调用链，也不写入业务文章。样本记录模型轮次、源码读取的累计传输字符、工具历史累计传输字符、首次预览、总耗时和 token。源码字段统计不包含初始选区片段；该片段已经在初始状态中提供。写入流提前结束可能收不到终帧用量，此时分别保存已报告的部分用量和本地估算，并标记缺失轮数。

对照结果和完整检查记录见 [源码协议验收记录](SOURCE_AGENT_ACCEPTANCE.md)。
