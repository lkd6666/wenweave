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

## 4. 安装 Python 依赖并启动

在宝塔终端执行：

```bash
cd /www/wwwroot/yibanpaiban/backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
mkdir -p data/uploads
chown -R www:www /www/wwwroot/yibanpaiban
```

在宝塔“Python 项目”中新增项目，项目路径选择 `backend`，运行用户选择 `www`，启动命令填写：

```bash
/www/wwwroot/yibanpaiban/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 2 --no-proxy-headers
```

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

配置中的 `proxy_buffering off` 和 900 秒超时不能删除，否则对话式排版的 SSE 流会被 Nginx 缓冲或提前断开。`client_max_body_size 35m` 与应用的 30 MB 文件导入限制配套。

## 6. 数据与升级

- 未配置对象存储时，上传内容位于 `backend/data/uploads`。单机部署需定期备份该目录；多实例部署需使用共享存储或对象存储。
- 升级前先停止应用，备份 MySQL 与 `backend/data/`，再替换代码和 `frontend/dist`。保留生产 `.env` 与数据目录，不要用发布包覆盖它们。
- 重新启动后访问 `/api/health/ready`；如果状态为 `degraded`，查看 Python 项目或 Supervisor 日志，并优先检查数据库连通性和生产环境变量。
