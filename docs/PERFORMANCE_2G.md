# 2 核 2 GiB 部署与资源检查

建议部署环境为单 Uvicorn worker、MySQL 与 SearXNG 同机、同时 1–2 个排版任务。建议将 Agent 全局并发设为 2、单用户并发设为 1，使用 SQLAlchemy 连接池 5 且无 overflow、SearXNG 单 worker/单线程/320 MiB 上限。应用的 Agent 并发默认值是 10 / 3，小内存部署须在 `backend/.env` 中显式覆盖：

```dotenv
CHAT_AGENT_MAX_CONCURRENT_RUNS=2
CHAT_AGENT_MAX_CONCURRENT_RUNS_PER_USER=1
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=0
```

MySQL 小内存起点见 [`deploy/mysql-2g.cnf.example`](../deploy/mysql-2g.cnf.example)。

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
