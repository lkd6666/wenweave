# 常规 Linux 部署

本指南适用于不使用宝塔面板的 Ubuntu/Debian 服务器，部署结构为 Nginx + systemd + Python 3.11+ + MySQL 5.7/8.0。发布 ZIP 已预构建 `frontend/dist`，服务器不需要 Node.js。示例域名为 `example.com`，安装目录为 `/opt/yibanpaiban`，后端仅监听 `127.0.0.1:8001`；请按实际情况替换。

不要把个人私有 `.7z` 备份上传到生产服务器。它包含完整数据库、环境变量、密钥和上传文件。

## 1. 安装系统依赖并创建运行用户

使用具有 `sudo` 权限的账号执行。请确保 `python3 --version` 为 3.11 或更高版本；不同发行版的软件包名称可能不同。

```bash
sudo apt update
sudo apt install -y nginx mysql-server python3 python3-venv unzip curl
sudo useradd --system --create-home --home-dir /var/lib/yibanpaiban --shell /usr/sbin/nologin yibanpaiban
sudo install -d -o yibanpaiban -g yibanpaiban /opt/yibanpaiban
```

生产服务器只需要开放 SSH、HTTP 和 HTTPS。不要向公网开放 8001 或 MySQL 的 3306 端口。

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

## 2. 上传发布包并创建持久化目录

上传 `yibanpaiban-release-<version>.zip` 及对应 `.sha256` 文件后，先校验再解压：

```bash
cd /tmp
sha256sum -c yibanpaiban-release-<version>.zip.sha256
sudo unzip yibanpaiban-release-<version>.zip -d /opt/yibanpaiban
sudo install -d -o yibanpaiban -g yibanpaiban /var/lib/yibanpaiban/data/uploads
sudo ln -s /var/lib/yibanpaiban/data /opt/yibanpaiban/backend/data
sudo chown -R yibanpaiban:yibanpaiban /opt/yibanpaiban
```

`backend/data/uploads` 是未配置对象存储时的上传持久化目录。上例把它放在代码目录外，便于版本升级；`backend/data/encryption.key` 也会在此保存。若使用 Docker、LVM 或云盘，请将 `/var/lib/yibanpaiban/data` 作为持久化卷并定期备份。

## 3. 创建数据库和最小权限账号

本步骤会导入发布包中的无数据 DDL。登录 MySQL 后执行：

```sql
CREATE DATABASE yibanpaiban CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'yibanpaiban'@'127.0.0.1' IDENTIFIED BY 'replace-with-a-long-password';
GRANT ALL PRIVILEGES ON yibanpaiban.* TO 'yibanpaiban'@'127.0.0.1';
FLUSH PRIVILEGES;
```

导入架构：

```bash
mysql -u root -p yibanpaiban < /opt/yibanpaiban/deploy/mysql-schema.sql
```

`deploy/mysql-schema.sql` 只含表、索引和约束，不包含用户、API Key、对象存储凭据、文档、日志或其他业务数据。MySQL 建议将 `max_allowed_packet` 设为至少 `64M`。

## 4. 配置生产环境

复制示例并限制权限：

```bash
sudo -u yibanpaiban cp /opt/yibanpaiban/backend/.env.example /opt/yibanpaiban/backend/.env
sudo chmod 600 /opt/yibanpaiban/backend/.env
```

先填写数据库、管理员账号、域名等值，至少包含：

```dotenv
APP_ENV=production
DATABASE_URL=mysql+pymysql://yibanpaiban:replace-with-a-long-password@127.0.0.1:3306/yibanpaiban?charset=utf8mb4
DEFAULT_ADMIN_USERNAME=replace-admin-name
DEFAULT_ADMIN_PASSWORD=replace-with-a-long-password
CORS_ORIGINS=https://example.com
TRUSTED_PROXY_CIDRS=127.0.0.1/32
```

下一步创建虚拟环境后，再生成随机密钥填入 `.env`。首次启动只会在用户表为空时创建管理员，首次登录后应立即修改密码。`.env` 和 `/var/lib/yibanpaiban/data` 均为私密运行时数据，不应提交、复制进新发布包或提供给其他人。

如果公网链路是 `CDN -> 雷池 -> Nginx -> Uvicorn`，后端可以自行从 `X-Forwarded-For` 还原客户端 IP，但必须将整个代理链上的节点受限地列入信任网段。例如 Nginx 代理到本机 Uvicorn，雷池位于 Docker `172.18.0.0/16`，CDN 的官方出口网段为 `198.51.100.0/24` 时：

```dotenv
TRUSTED_PROXY_CIDRS=127.0.0.1/32,172.18.0.0/16,198.51.100.0/24
```

代码会从右向左跳过 Nginx、雷池和 CDN，记录第一个非可信地址（即访客 IP）。实际部署中必须以雷池容器/回源网段和 CDN 官方 IP 段替换示例值，不要使用 `0.0.0.0/0`。同时需确认雷池未丢弃 `X-Forwarded-For`；若 CDN 未传入访客地址，后端无法从 CDN IP 反推出真实访客。

### 启动 SearXNG 搜图服务

搜图是独立可降级功能。服务器已安装 Docker Compose 时，按发布包中的固定镜像摘要启动：

```bash
cd /opt/yibanpaiban/deploy/searxng
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

保持 `backend/.env` 中的 `SEARXNG_BASE_URL=http://127.0.0.1:8088`。如需改端口，同时修改 `deploy/searxng/.env` 的 `SEARXNG_HOST_PORT` 与此地址。默认国内来源为百度图片、搜狗图片和 `cn.bing.com` 图片；百度候选仅安全升级其 HTTP 来源页为 HTTPS，原图仍必须通过现有 HTTPS 校验。生产切换前按 `deploy/searxng/README.md` 在 `127.0.0.1:8089` 运行隔离验证，验证通过后执行 `./apply-domestic-profile.sh`；该脚本会保留搜图密钥并创建可回滚备份。应用层搜图总等待预算默认 4 秒，规范化结果缓存 300 秒，可分别用 `SEARXNG_TIMEOUT_SECONDS` 与 `SEARXNG_SEARCH_CACHE_SECONDS` 调整。该容器端口只绑定回环地址，不要通过防火墙或 Nginx 暴露。未启动或暂时故障时仅搜图返回错误，编辑、AI 生图和其他功能继续可用。

默认以低配机模式运行：单 worker、单线程、320 MiB 内存上限、160 MiB 预留和 96 个 PID。可在 `deploy/searxng/.env` 覆盖 `SEARXNG_MEMORY_LIMIT`、`SEARXNG_UWSGI_WORKERS` 等参数。2C2G 仅适合低并发且数据库外置的场景；MySQL、主应用与搜图都在同机时建议至少 4G 内存。

## 5. 安装 Python 依赖并配置 systemd

```bash
cd /opt/yibanpaiban/backend
sudo -H -u yibanpaiban python3 -m venv venv
sudo -H -u yibanpaiban ./venv/bin/pip install --upgrade pip
sudo -H -u yibanpaiban ./venv/bin/pip install -r requirements.txt
sudo ./venv/bin/python -m playwright install-deps chromium
sudo -H -u yibanpaiban ./venv/bin/python -m playwright install chromium
sudo -H -u yibanpaiban ./venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
sudo -H -u yibanpaiban ./venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将最后两个命令的输出分别填入 `.env` 的 `SECRET_KEY` 与 `ENCRYPTION_KEY`，再继续创建 systemd 服务。

官方微信合规检测由 Python Playwright 启动 Chromium，不需要 Node.js。浏览器必须使用运行 systemd 服务的同一用户安装；`sudo -H` 确保它进入该用户的缓存目录，而不是误装到 `/root/.cache/ms-playwright`。每次升级或重装 Python 依赖后都要重新执行 Chromium 安装命令并重启服务，以保持浏览器 revision 与 Playwright 版本一致。浏览器仅在首次模型合规检测时启动并由该应用进程复用；浏览器安装失败时文章会显示“未验证”，但编辑、保存和公众号草稿同步不会被阻断。若运维已通过系统包安装 Chromium，可在 `backend/.env` 设置 `WECHAT_COMPLIANCE_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium`（按实际路径替换），无需再下载 Playwright 管理的浏览器。

创建 `/etc/systemd/system/yibanpaiban.service`：

```ini
[Unit]
Description=Yibanpaiban FastAPI service
After=network.target mysql.service
Wants=network-online.target

[Service]
Type=simple
User=yibanpaiban
Group=yibanpaiban
WorkingDirectory=/opt/yibanpaiban/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/yibanpaiban/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers --log-config /opt/yibanpaiban/backend/uvicorn-log.json
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

启动服务并检查就绪状态：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now yibanpaiban
sudo systemctl status yibanpaiban --no-pager
curl http://127.0.0.1:8001/api/health/ready
```

若启动失败，使用 `sudo journalctl -u yibanpaiban -e --no-pager` 查看日志，优先检查 MySQL 连接、`.env` 权限和生产密钥。不要移除 `--no-proxy-headers`；应用仅会信任 `TRUSTED_PROXY_CIDRS` 中的反向代理地址。

## 6. 配置 Nginx 与 HTTPS

安装发布包中的通用 Nginx 配置，替换域名后启用：

```bash
sudo cp /opt/yibanpaiban/deploy/nginx.conf.example /etc/nginx/sites-available/yibanpaiban
sudo sed -i 's/example.com/your-domain.example/g' /etc/nginx/sites-available/yibanpaiban
sudo ln -s /etc/nginx/sites-available/yibanpaiban /etc/nginx/sites-enabled/yibanpaiban
sudo nginx -t
sudo systemctl reload nginx
```

该配置反向代理前端和 API，应用自身托管 `frontend/dist`。其中 SSE 专用路由会关闭代理/请求缓冲与 gzip，并强制下发 `no-store` 缓存策略；不得删除。若 CDN 有“强制缓存”“缓存一切”一类规则，另需将 `/api/documents/*/chat-runs/*/events` 配为绕过缓存，否则 CDN 规则可能覆盖源站响应头。`client_max_body_size 35m` 与应用的 30 MB 文档导入限制配套。

申请证书后将 HTTP 重定向到 HTTPS。以 Certbot 为例：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.example --redirect
```

访问 `https://your-domain.example/api/health/ready`，再完成管理员首次登录。若前端与 API 使用不同域名，`CORS_ORIGINS` 必须填写真实的 HTTPS 前端域名。

## 7. 备份、升级与日常维护

升级前停止服务并备份数据库、`.env` 和持久化目录：

```bash
sudo systemctl stop yibanpaiban
mysqldump -u yibanpaiban -p --single-transaction --routines --events --triggers yibanpaiban > yibanpaiban-$(date +%F).sql
sudo tar -C /var/lib/yibanpaiban -czf yibanpaiban-data-$(date +%F).tar.gz data
```

解压新发布包前保留 `/opt/yibanpaiban/backend/.env`，并继续挂载原来的 `/var/lib/yibanpaiban/data`。替换代码、重新安装 `requirements.txt` 中新增的依赖后，执行：

```bash
sudo systemctl start yibanpaiban
curl http://127.0.0.1:8001/api/health/ready
sudo systemctl reload nginx
```

完成后确认首页、文件上传、SSE 对话和管理员登录均正常；数据库或运行时数据升级前始终保留可恢复的备份。
