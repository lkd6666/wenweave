# 宝塔面板部署

本项目的发布包已包含 `frontend/dist`，宝塔服务器只需要 Python 3.11+、Nginx 和 MySQL 5.7/8.0，不需要安装 Node.js。以下示例使用站点目录 `/www/wwwroot/yibanpaiban`、域名 `example.com` 和应用端口 `127.0.0.1:8001`；请替换为实际值。

## 1. 安装并上传

1. 在宝塔软件商店安装 **Nginx**、**MySQL 5.7 或 8.0** 与 **Python 项目管理器**（或 Supervisor）。
2. 在服务器上创建站点目录 `/www/wwwroot/yibanpaiban`，上传并解压 `yibanpaiban-release-<version>.zip` 到该目录。
3. 确认解压后存在 `backend/`、`frontend/dist/`、`deploy/mysql-schema.sql` 和本文件。

不要上传个人私有 `.7z` 备份包到公共服务器；其中包含数据库、密钥和环境变量。

## 2. 创建 MySQL 数据库

在宝塔的“数据库”页面创建独立数据库和用户，例如：

```sql
CREATE DATABASE yibanpaiban CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'yibanpaiban'@'127.0.0.1' IDENTIFIED BY 'replace-with-a-long-password';
GRANT ALL PRIVILEGES ON yibanpaiban.* TO 'yibanpaiban'@'127.0.0.1';
FLUSH PRIVILEGES;
```

通过宝塔数据库管理器导入 `deploy/mysql-schema.sql` 到新库。该文件只有表、索引和约束定义，不包含任何业务数据、账号、模型 API Key 或对象存储凭据。

## 3. 配置生产环境

在站点终端执行：

```bash
cd /www/wwwroot/yibanpaiban/backend
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

把两个命令的输出分别填入 `.env` 的 `SECRET_KEY` 和 `ENCRYPTION_KEY`，再配置以下值：

```dotenv
APP_ENV=production
DATABASE_URL=mysql+pymysql://yibanpaiban:replace-with-a-long-password@127.0.0.1:3306/yibanpaiban?charset=utf8mb4
DEFAULT_ADMIN_USERNAME=replace-admin-name
DEFAULT_ADMIN_PASSWORD=replace-with-a-long-password
CORS_ORIGINS=https://example.com
TRUSTED_PROXY_CIDRS=127.0.0.1/32
```

`.env`、`backend/data/` 和 `backend/data/encryption.key` 是运行时私密文件。限制站点目录权限，且不要把它们下载、上传或提交到 Git。首次启动仅在用户表为空时创建上述管理员；首次登录后立即修改密码。

对于 `CDN -> 雷池 -> 宝塔 Nginx -> Uvicorn` 链路，请在 `TRUSTED_PROXY_CIDRS` 中按照链路填写宝塔 Nginx 到 Uvicorn 的地址、雷池回源网段及 CDN 官方出口网段。例如：

```dotenv
TRUSTED_PROXY_CIDRS=127.0.0.1/32,172.18.0.0/16,198.51.100.0/24
```

后端会在受信任的 `X-Forwarded-For` 链中从右向左跳过这些代理，以最左边的非代理 IP 作为操作日志的客户端 IP。用实际雷池回源网段和 CDN 官方 IP 段代替示例值，不要配置 `0.0.0.0/0`。需保证雷池将 CDN 传入的 `X-Forwarded-For` 继续透传到 Nginx；如果该头被丢弃，后端只能拿到 CDN/雷池 IP。

### 启动 SearXNG 搜图服务

在已安装 Docker Compose 的宝塔终端执行：

```bash
cd /www/wwwroot/yibanpaiban/deploy/searxng
cp settings.yml.example settings.yml
SECRET=$(openssl rand -hex 32)
sed -i "s/replace-with-a-random-64-character-secret/$SECRET/" settings.yml
chmod 600 settings.yml
printf 'SEARXNG_HOST_PORT=8088\nSEARXNG_SECRET=%s\n' "$SECRET" > .env
chmod 600 .env
docker compose pull
docker compose up -d
curl -fsS 'http://127.0.0.1:8088/search?q=test&categories=images&format=json' >/dev/null
```

保持 `SEARXNG_BASE_URL=http://127.0.0.1:8088`。如需改端口，同时修改 `deploy/searxng/.env` 的 `SEARXNG_HOST_PORT` 与此地址。默认国内来源为百度图片、搜狗图片和 `cn.bing.com` 图片；百度候选仅安全升级其 HTTP 来源页为 HTTPS，原图仍必须通过现有 HTTPS 校验。生产切换前按 `deploy/searxng/README.md` 在 `127.0.0.1:8089` 运行隔离验证，验证通过后执行 `./apply-domestic-profile.sh`；该脚本会保留搜图密钥并创建可回滚备份。应用层搜图总等待预算默认 4 秒，规范化结果缓存 300 秒，可分别用 `SEARXNG_TIMEOUT_SECONDS` 与 `SEARXNG_SEARCH_CACHE_SECONDS` 调整。不要在宝塔安全组、Nginx 或公网防火墙开放该端口。搜图服务停机不会阻止主应用启动。

Compose 默认使用单 worker、单线程和 320 MiB 内存上限（160 MiB 预留、96 PID），可通过 `deploy/searxng/.env` 的 `SEARXNG_MEMORY_LIMIT`、`SEARXNG_UWSGI_WORKERS` 等变量调整。2C2G 仅适合低并发且数据库外置的场景；宝塔、MySQL、主应用和搜图同机部署建议至少 4G 内存。

## 4. 安装 Python 依赖并启动

在宝塔终端执行：

```bash
cd /www/wwwroot/yibanpaiban/backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m playwright install-deps chromium
install -d -m 0755 -o www -g www /home/www
sudo -H -u www ./venv/bin/python -m playwright install chromium
mkdir -p data/uploads
chown -R www:www /www/wwwroot/yibanpaiban
```

官方微信合规检测使用 Python Playwright Chromium，不需要 Node.js。`install-deps` 需要 root 权限；浏览器文件则必须使用实际运行 Uvicorn 的 `www` 用户安装。不要只用 root 执行 `playwright install`，否则文件会进入 `/root/.cache/ms-playwright`，而 `www` 进程仍会在 `/home/www/.cache/ms-playwright` 报浏览器不存在。若系统没有 `sudo`，等效命令为 `runuser -u www -- env HOME=/home/www ./venv/bin/python -m playwright install chromium`。

每次升级或重装 `requirements.txt` 后都要重新执行上面的 Chromium 安装命令，确保浏览器 revision 与固定的 Python Playwright 版本一致，然后在宝塔面板重启 Python 项目。可在重启前以运行用户执行真实启动测试：

```bash
sudo -H -u www ./venv/bin/python -c 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); print("Chromium OK:", p.chromium.executable_path); b.close(); p.stop()'
```

浏览器只在首次模型合规检测时启动并由进程复用；不可用时返回“未验证”，不会阻止编辑、保存或公众号草稿同步。若服务器已有系统 Chromium，可在 `backend/.env` 设置 `WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH=/实际/chromium路径`。

在宝塔“Python 项目”中新增项目，项目路径选择 `backend`，运行用户选择 `www`，启动命令填写：

```bash
/www/wwwroot/yibanpaiban/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers --log-config /www/wwwroot/yibanpaiban/backend/uvicorn-log.json
```

生产环境只启动一个 Uvicorn worker。Agent 的数据库准入并发保持由
`CHAT_AGENT_MAX_CONCURRENT_RUNS` 和 `CHAT_AGENT_MAX_CONCURRENT_RUNS_PER_USER`
控制，不要通过增加 worker 数量来扩大 Agent 并发。若实际站点使用
`/www/wwwroot/ybpb.dycz.cn` 和端口 `8010`，请将上面的目录和端口替换为实际值，完整命令为：

```bash
/www/wwwroot/ybpb.dycz.cn/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 --workers 1 --no-proxy-headers --log-config /www/wwwroot/ybpb.dycz.cn/backend/uvicorn-log.json
```

保存启动命令后，只能通过宝塔 Python 项目服务停止并启动应用，不要在 SSH 中额外使用
`nohup` 启动 Uvicorn。重启前后执行 `pgrep -af 'uvicorn app.main:app'`；若宝塔停止后仍有旧
PID，先在面板停止对应项目，确认业务无请求后再由运维执行 `kill -TERM <旧 PID>`，随后只从
宝塔启动一次。不要使用 `kill -9` 测试或清理 worker。

`uvicorn==0.37.0` 支持 `--timeout-worker-healthcheck`。当前单 worker 不需要该参数；未来若
服务器内存已升级到至少 4 GiB 并恢复多 worker，启动命令必须显式增加
`--timeout-worker-healthcheck 30`。

若面板版本没有 Python 项目管理器，用 Supervisor 创建同样的启动命令，并设置开机启动和异常自动重启。不要暴露 8001 端口到公网。

启动后应用会校验生产密钥、连接 MySQL、补齐 schema，并创建首个管理员。执行以下命令应返回 `status: ok`：

```bash
curl http://127.0.0.1:8001/api/health/ready
```

## 5. 配置 Nginx 和 HTTPS

1. 在宝塔“网站”中新建 `example.com` 站点，根目录保持 `/www/wwwroot/yibanpaiban`。
2. 将 `deploy/baota-nginx.conf.example` 的 `server` 配置合并到站点 Nginx 配置，替换域名和目录中的示例值。
3. 保存后在宝塔执行 Nginx 配置检查并重载 Nginx。
4. 在“SSL”页申请并强制启用 HTTPS；外网防火墙只放行 80 和 443。
5. 打开 `https://example.com/api/health/ready`，再访问首页并完成管理员首次登录。

配置中的 SSE 专用路由会关闭代理/请求缓冲与 gzip，并强制下发 `no-store` 缓存策略，不能删除。若 CDN 有“强制缓存”“缓存一切”一类规则，另需将 `/api/documents/*/chat-runs/*/events` 配为绕过缓存，否则 CDN 规则可能覆盖源站响应头。`client_max_body_size 35m` 与应用的 30 MB 文件导入限制配套。

## 6. 数据与升级

- 未配置对象存储时，上传内容位于 `backend/data/uploads`。单机部署需定期备份该目录；多实例部署需使用共享存储或对象存储。
- 升级前先停止应用，备份 MySQL 与 `backend/data/`，再替换代码和 `frontend/dist`。保留生产 `.env` 与数据目录，不要用发布包覆盖它们。
- 重新启动后访问 `/api/health/ready`；如果状态为 `degraded`，查看 Python 项目或 Supervisor 日志，并优先检查数据库连通性和生产环境变量。

## 7. Agent 卡住或 worker 退出取证

本版本会在每个 Uvicorn worker 启用 Python `faulthandler`：向具体 worker 发送 `SIGUSR2` 会把该进程全部线程栈写入 Python 项目/Supervisor 的错误日志；正常退出也会留下 PID 与 worker ID。启动时会记录 RSS 基线。`SIGKILL` 无法被 Python 捕获，因此出现进程消失时要用一次性信号跟踪确认外部来源。

为避免前端静态资源、健康检查和轮询刷屏，worker 日志默认不输出成功的 `GET`、`HEAD`、`OPTIONS` access log；4xx/5xx 仍会保留。未处理的请求、线程和 asyncio 任务异常均会输出完整 traceback，并带 PID、worker ID 与请求 ID（请求异常）。

先从宝塔终端确认唯一的 Uvicorn PID（不要选 Nginx，也不要停止应用）：

```bash
pgrep -af 'uvicorn app.main:app'
kill -USR2 <uvicorn-pid>
```

复现一次问题前，以 root 或具备 ptrace 权限的运维账号附加 `strace`；这只跟踪信号和进程事件，不会修改代码、数据库或 Nginx：

```bash
strace -ff -tt -s 160 -e trace=signal,process -p <uvicorn-pid> -o /tmp/yibanpaiban-agent-<uvicorn-pid>.strace
```

复现后，用 `Ctrl-C` 停止 `strace` 本身，再检查 `/tmp/yibanpaiban-agent-<uvicorn-pid>.strace*` 和 Python 项目/Supervisor 错误日志。若记录到 `SIGKILL`、`SIGTERM` 或父进程退出，结合对应时间点的宝塔/Supervisor/systemd 日志即可定位外部终止来源；不要把 `kill -9` 用于测试中的 worker。
