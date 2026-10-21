# 模型提示缓存优化

模型级 `prompt_cache_enabled` 控制 OpenAI 兼容 / Responses 的稳定缓存键和请求结构优化，也支持 Anthropic 原生缓存边界及相同的状态分离。默认值不变，逐个验证、逐个开启；Gemini 原生接口继续使用原提示传递方式。

开启后的请求顺序为：固定 system、历史及当前用户请求、完整工具调用与结果、唯一的最新运行状态。文档 revision、地图、选中元素、参考模板、排版设置及工作记忆由当前工作区生成。只读轮次复用状态，revision 或工具结果预算变化后重新生成。

最新状态在内部是带标记的 Human 消息，只存在于待发送投影；GPT / o 系列在 OpenAI 序列化时将它承载为助手资料消息，其他模型使用用户资料消息，避免 DeepSeek 推理字段约束或火山助手预填协议报错。OpenAI 兼容 / Responses 每组连续工具结果后插入一条固定的「服务端工具结果边界」用户资料消息，为网关提供可复用的消息结束点。这些边界由实际历史确定，下一轮保持原位置；不会拆开并行工具结果，也不包含 revision 或文档内容。不增加工具定义或伪造工具调用。

Anthropic 开启后，固定 system、工具定义末尾及最近一条有文本的历史消息使用原生 `cache_control`；不在动态状态上设边界，也不插入上述 OpenAI 分隔消息，正常使用三个缓存槽位。历史边界只在待发送副本上添加，ToolMessage 的提示由 SDK 提升到对应 tool_result 块；一小时 TTL 不受支持时沿用已有默认 TTL 回退。

跨任务恢复通过 `AgentContextBuilder` 保留有明确来源的事件账本中的原始工具结果，不随当前 revision 重写，避免破坏已缓存前缀。预算缩小时仍按当前额度截断，旧格式或关闭开关时沿用过期摘要。固定规则明确历史源码只供参考，编辑仍须匹配最新 revision，失效时重新读取；写工具的 revision / hash 校验继续执行。DeepSeek 实际上报的 `reasoning_content` 随工具调用写入事件及暂停恢复数据并按预算计数，兼容接口重放这一原生字段，不伪造推理。

网关收到的消息不含内部标记。最新状态和边界都不进入聊天记录、持久事件、压缩摘要或恢复数据，也不被后端识别为新用户请求。固定规则明确它们是资料，不能扩大授权或表示任务已经完成。暂停、重启、旧格式恢复均从当前工作区和完整工具配对重新生成投影。运行摘要也投影为助手历史，内部保留摘要类型。

预检使用完整状态构建器；运行时请求检查、工具结果预算和压缩都预留状态与边界空间。状态只计一次；每组工具结果只计一条边界，并行调用不会重复计算。预检将边界计入相应完整助手工具轮，运行统计单列「工具轮分隔资料」。压缩保留固定规则、真实请求、最新状态及完整工具配对，按压缩后保留的循环重建边界。必要内容无法容纳时明确失败，不裁掉状态或固定规则。

所有提供方和开关路径在完整且通过 schema 校验的写工具参数生成后，最多等待 2 秒收集正常结束帧及 usage，以免关闭流导致用量缺失或缓存未完成写入；正常结束保留原始 Responses 项和 metadata。网关漏掉结束帧时仍可执行已校验的写入，不会为等 usage 无限阻塞或重试同一写入，也不会把缺失用量估算入账。恢复出的写入保留已经收到的真实推理字段。

旧块协议继续使用 `yb-agent-v1-p{provider}-m{model}-s{shard}` 键及 16 分片策略。源码 `v2` 协议在相同基础键上追加 `-src2-{工具schema指纹}`，为每个实际工具组合提供稳定路由，不包含文章、revision、选区或用户请求。指纹覆盖工具名、说明、参数结构与顺序；重复加载、传入组顺序不同、连续写入、恢复或新任务使用同一工具组合时保持一致。不发送 `prompt_cache_breakpoint`。关闭开关即可恢复旧提示路径，无需清理历史。

源码协议保留 `enable_tool_groups` 的按需加载。核心工具固定在前，专用组按 images、history、themes 顺序添加；加载组不会扩大用户授权，也不会提前暴露全部专用工具。新增组改变网关前缀，因此切换后的首个请求可能没有命中；后续相同组合可以复用。这种真实 schema 变化不能仅通过固定 system 或缓存键消除。

唯一的源码运行状态包含当前 `loaded_tool_groups`。文章 revision、工具预算或组集合变化后重新生成，只读轮次复用。预检和恢复预算使用同一集合；增加 schema 后根据原始输入额度重新计算可用消息预算，重复加载不扣减额度。并行加载组串行合并，避免丢失组或绑定过期 schema。

统一用量解析器逐字段合并规范化 usage 与原始 metadata，保留明确零值，支持 default / priority / flex、DeepSeek 原生缓存读取，以及 Anthropic 原生和规范化计数。读取、写入分别统计；总量别名与层级别名不重复相加。原生 Anthropic 的未缓存输入须加缓存读写，规范化输入已包含缓存部分。未上报 usage 的请求不估算入账，历史不回填。API、数据库结构和命中率公式保持原样。

每次完成模型请求记录 `prompt_cache_diagnostic`：策略、system 指纹、状态 token 估计、缓存读写、首个有效输出耗时、请求总耗时、工具协议、实际工具 schema 指纹及 schema token 估计、状态的网关角色、历史指纹及消息数、usage 是否上报。日志不包含正文、模板源码、缓存键或凭据。缺 usage 的读写字段为 null。

2026-10-12 的本地验收仅启用了一个已配置的 Responses 模型，并未改变其他模型的开关。该次报告保存在本地 `outputs/cache-optimization-20261012/report.md`。`outputs/` 为被 Git 忽略的诊断产物目录，不随源码分发；合成测试的比例不作为生产命中率承诺。

2026-10-17 新增多供应商协议适配与跨任务稳定历史。真实 Agent 基准使用 JSON 事件及生产 `AgentContextBuilder` 重建第二个任务，不能直接复用观测器中的内存消息或传输层缓存提示。该次研究与逐调用对照保存在本地 `outputs/cache-provider-optimization-20261017/report.md`。基准中的开关覆盖仅作用于脱离 ORM 的测试配置，不批量修改持久模型配置。

以下脚本用于本地诊断，并非部署所需步骤。其中 `observe_prompt_cache.py`、`benchmark_source_prompt_cache.py --live` 和 `diagnose_source_prompt_cache.py` 保留了验收环境的固定模型 ID；后两者还校验网关或模型配置。在其他环境运行前须核对脚本与本机模型配置，真实调用可能产生费用。通用源码协议对照使用 `benchmark_source_agent.py --model-id` 指定自己的模型。

生产观察通过只读脚本更新报告，隔离验收流量按 `cache-acceptance-*` 排除：

```powershell
cd backend
python scripts/observe_prompt_cache.py
```

达到 30 次新上报生产 Agent 调用后，按输入 token 加权检查命中率，并同时检查延迟、压缩用量和实际编辑结果。不同文章和工具使用会改变输入量，不能直接把合成轨迹比例套用到业务请求。

出现状态错误、协议错误或输入明显增长时，在模型管理中关闭当前模型的「提示缓存优化」，或使用现有模型更新接口提交 `{"prompt_cache_enabled": false}`。用量修复继续生效。其他网关需先完成协议、相同轨迹和编辑回归验证，不能批量开启。

源码架构适配的离线轨迹和实际网关验证使用独立输出目录，包含按需加载、连续写入和真实压缩调用：

```powershell
cd backend
python scripts/benchmark_source_prompt_cache.py
python scripts/benchmark_source_prompt_cache.py --live
```

`--live` 比较当前模型在源码协议下关闭/开启优化的相同合成请求，覆盖压缩输入/输出消耗；仅执行脚本定义的内存编辑，网关输出不会用于业务文章或外部工具。结果保存在 `outputs/source-cache-adaptation-20261012/`。原块协议 benchmark 已明确固定为 `v1`，避免默认工具协议变化影响历史对照。

2026-10-13 全面验证增加真实 XHigh Agent 编辑、任务完成后的新要求，以及 24 个历史工具轮的等轨迹对照（包含真实压缩调用）：

```powershell
cd backend
python scripts/diagnose_source_prompt_cache.py actual --role native --suffix acceptance
python scripts/diagnose_source_prompt_cache.py comparison --suffix acceptance
```

结果保存到 `outputs/source-cache-comprehensive-20261013/`。实际 Agent 测试只修改内存中的合成稿，不写业务数据库；真实模型自行选择并执行工具。`comparison` 则以相同工具轨迹比较旧合并 system、原 Human 尾状态和当前优化投影。两者用途不同，均不能代表部署服务器的生产命中率。缓存路由、冷启动、schema 切换和压缩仍可能造成不命中；命中并不保证延迟下降。
