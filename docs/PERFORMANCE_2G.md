# 2 核 2 GiB 性能优化与验收记录

本轮目标环境是单 Uvicorn worker、MySQL 与 SearXNG 同机、同时 1–2 个排版任务。建议将 Agent 全局并发设为 2、单用户并发设为 1，使用 SQLAlchemy 连接池 5 且无 overflow、SearXNG 单 worker/单线程/320 MiB 上限。应用的 Agent 并发默认值是 10 / 3，小内存部署须在 `backend/.env` 中显式覆盖：

```dotenv
CHAT_AGENT_MAX_CONCURRENT_RUNS=2
CHAT_AGENT_MAX_CONCURRENT_RUNS_PER_USER=1
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=0
```

MySQL 小内存起点见 [`deploy/mysql-2g.cnf.example`](../deploy/mysql-2g.cnf.example)。

## 已完成的可重复本机对比

以下数据在 2026-09-22 的 Windows 开发机、项目虚拟环境中产生。它只度量本地流式处理 CPU，不包含模型网络等待，因此不会把外部模型波动算作收益。原始 JSON 保存在 `docs/performance-runtime-local.json`。

运行命令：

```powershell
cd backend
.\venv\Scripts\python.exe scripts\benchmark_runtime_performance.py `
  --html-chars 524288 --fragment-chars 2048 --rounds 3 `
  --output ..\docs\performance-runtime-local.json
```

固定 512 KiB HTML 参数被拆成 264 个分片。旧路径每个分片都尝试完整 JSON 解析并计算 token；新路径增量扫描 JSON，只在完整候选出现时解析，并按 250 ms 展示节奏及流结束边界计算 token。

| 指标 | 优化前 | 优化后 | 变化 |
| --- | ---: | ---: | ---: |
| 本地 CPU 中位数 | 4.391 s | 0.125 s | 降低 97.2% |
| 10 个同用户闲置 SSE 的稳态通知查询 | 10 次/秒 | 1 次/秒 | 降低 90% |
| 无通知订阅者 | 0 次/秒 | 0 次/秒 | 保持为 0 |
| 单个执行任务的租约续写 | 120 次/分钟 | 6 次/分钟 | 降低 95% |

通知和租约数据来自调度频率及自动化回归：通知测试验证 10 个标签页共享 broker、多个用户同轮只执行一条带权限过滤的 SELECT、最后一个订阅者离开后停止轮询；控制测试验证取消仍每 0.5 秒读取，而 42 次取消检查只触发 2 次续租。SQL 读写数量应在目标 MySQL 上再次用 `performance_schema.events_statements_summary_by_digest` 或慢查询采样核对。

快速模型分片另用 `scripts/benchmark_fast_model_stream.py` 测量。这个基准覆盖此前大参数测试没有覆盖的两条路径：兼容网关反复发送累计工具参数前缀，以及模型把普通文本拆成大量单字 chunk。结果保存在 `docs/performance-fast-stream-local.json`。

| 快速流场景 | 优化前 CPU 中位数 | 优化后 CPU 中位数 | 变化 |
| --- | ---: | ---: | ---: |
| 65,596 字符累计工具参数，2,050 个前缀 | 0.453 s | 0.031 s | 降低 93.1% |
| 20,000 个单字文本 chunk | 0.578 s | 0.031 s | 降低 94.6% |

工具参数超时检测现在只保留每个工具的最新定长签名，不再序列化并缓存全部历史前缀。文本和思考流按 40 ms 或 2,048 字符合并；响应 chunk 按 128 条分段汇总，服务端时间线在段落结束时一次拼接。HTTP API、SSE 事件名称、事件顺序和最终正文保持不变。

## 目标机整机复测

开发机不能替代 2 GiB Linux 主机的 OOM、swap 与 Chromium 子进程结论。部署后先记录 Uvicorn worker PID，再为每个场景运行资源采样器；另一个终端执行固定文章和脚本化模型输出。

```bash
cd /opt/yibanpaiban/backend
./venv/bin/python scripts/benchmark_host_resources.py \
  --pid "$(pgrep -n -f 'uvicorn app.main:app')" \
  --label idle-no-clients --duration 60 \
  --output ../benchmark-2g.jsonl
```

依次使用标签 `idle-no-clients`、`idle-10-sse`、`single-run`、`double-run-search`、`long-conversation`、`large-tool-arguments`、`idle-120s-after-compliance`。每个场景保留相同文章、模型输出和运行时长。`double-run-search` 必须同时触发两个不同用户的排版任务与一次搜图；本方案将单用户并发设为 1，不能用同一账号伪造双任务。

验收时记录：整机最低 `MemAvailable`、应用进程树峰值 RSS/Swap、MySQL 与 SearXNG 容器峰值、各阶段耗时、模型等待、本地处理耗时、SQL digest 次数、浏览器子进程数。任务结束 120 秒后 Chromium/Playwright 子进程应消失；连续 20 轮后进程数、参考排版缓存条目和存活任务数应稳定。普通文章的结果不能替代超大文档边界测试。

前端用同一固定事件脚本分别测试前台与隐藏页。记录 Chrome Performance 中的长任务，覆盖流式活动消息、历史消息、长文变短文、图片加载、容器宽度变化和暗色模式；隐藏页仍应处理完成事件和待确认通知，纯展示倒计时、预览测量与工作台 AI 状态刷新应暂停，回到前台后立即同步。

## 回滚边界

各组改动保持独立：资源默认值在 `.env`；索引有独立 SQL 迁移；通知 broker、Agent SSE 缓存、流式参数 buffer、Chromium 回收、前端可见性处理分别位于独立模块。发布前备份数据库和 `.env`，执行迁移并验证启动恢复；回滚代码时保留新增索引不会改变 API 或业务数据格式。
