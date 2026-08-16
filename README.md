# 微信公众号 AI 排版系统

本地可运行的「AI 公众号排版系统」，支持 AI 模型/密钥统一管理、PDF/Word 导入并自动提取图片到对象存储（阿里云 OSS、腾讯云 COS、华为云 OBS、火山引擎 TOS、七牛云 Kodo；未配置时自动切换为完整本地存储模式）、类 Claude Code 的多轮对话式 HTML 排版编辑、实时预览、一键复制代码，以及基础用户权限管理。

## 功能概览

- **用户与权限**：管理员 / 普通用户两级角色，支持用户组与按用户/用户组限制模型可用范围，JWT 登录鉴权
- **AI 模型管理**（管理员）：内置主流 Provider/模型预设，自动填写官方 Base URL、协议、思考参数；可加密存储 API Key、拉取模型列表并测试连通性
- **存储设置**（管理员）：支持阿里云 OSS、腾讯云 COS、华为云 OBS、火山引擎 TOS、七牛云 Kodo；未配置时自动切换为完整的服务器本地存储模式
- **公众号草稿同步**：管理员可维护多个公众号 AppID/AppSecret，并按用户或用户组授予推送权限；编辑器支持标题、作者、摘要、原文链接、封面裁剪和评论选项，一键创建公众号草稿并保留推送记录
- **文档导入**：支持 PDF / Word(.docx) 在浏览器本地解析；OSS 未配置时，回退为受控服务器上传
- **对话式排版**：多轮对话 + 工具调用（局部替换 / 整体重写 / 合规自检），SSE 流式输出
- **统一配图**：通过 SearXNG 搜索互联网图片，或使用已配置的 AI 图片模型生成候选并应用到封面、正文和现有图片
- **Agent 编排**：基于 LangGraph 的 `model -> tools -> model` 图，实时转发 token、工具调用和源码更新
- **排版工作台**：对话面板、实时预览、合规检测面板、源码编辑与复制
- **高效版本历史**：采用内容寻址、压缩快照与增量提交；相同正文只保存一次，连续增量自动限制回放深度
- **微信合规引擎**：基于微信编辑器源码逆向分析的规则检测（Python + Node.js 双实现）
- **主题模板画廊**：内置六套 `gzh-design-skill` 主题预览，支持完整、克制和关键组件三种套用强度，以及本次排版补充要求

## 主题模板与第三方源码

编辑器工具栏中的「主题模板」会打开可视化画廊。选择主题后可设定套用强度并填写补充要求；系统先绑定当前文档校验和并要求确认，再由 Agent 执行全文排版。主题任务会同时通过上游严格 HTML 检查和现有微信兼容性检查，任何上游 ERROR 都不会覆盖文档或创建版本。

上游 `gzh-design-skill` 以固定源码快照存放在 `_third_party/gzh-design-skill`，包含其原始版权和 AGPL-3.0 许可证。部署包应随附该目录及本项目集成源码，内部网络使用者可取得对应源码。详情见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 环境要求

- Python 3.11+
- Node.js 18+
- （可选）Node.js 用于运行 `wechat_format_rules_source.js` 命令行校验工具

## 快速开始

### 1. 后端

```bash
cd backend

# 创建虚拟环境（首次）
python -m venv venv

# 激活虚拟环境
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 复制环境变量并填写 MySQL DATABASE_URL（必填）
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux

# 启动后端（默认 http://127.0.0.1:8001）
uvicorn app.main:app --reload --no-proxy-headers --host 127.0.0.1 --port 8001
```

首次启动会自动：
- 连接 MySQL 并创建所需数据表（需先配置 `DATABASE_URL`）
- 生成加密密钥 `backend/data/encryption.key`（若未配置 `ENCRYPTION_KEY`）
- 创建默认管理员账号（见下方默认凭据）

### 2. 前端（开发模式）

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 http://localhost:5173 ，Vite 会将 `/api` 请求代理到后端 `http://127.0.0.1:8001`。

### 3. 默认管理员账号

| 字段 | 默认值 |
|------|--------|
| 用户名 | `admin` |
| 密码 | `admin123` |

**首次登录后请立即修改密码。**

## 生产构建（单体部署）

```bash
cd frontend
npm run build        # 产物输出到 frontend/dist

cd ../backend
uvicorn app.main:app --no-proxy-headers --host 0.0.0.0 --port 8001
```

后端会自动托管 `frontend/dist` 静态文件，访问 http://127.0.0.1:8001 即可使用完整应用。

## 发布与部署

发布包和个人加密备份由 `scripts/package-release.ps1` 生成。发布包不包含 `.env`、数据库、上传文件、加密密钥或 Git 元数据；个人备份使用 AES-256 加密的 `.7z`，包含当前 MySQL 逻辑备份和运行时数据。

完整的部署步骤、Nginx SSE 配置和升级说明见：

- [宝塔面板部署](docs/DEPLOY_BAOTA.md)
- [常规 Linux 部署（systemd + Nginx）](docs/DEPLOY_LINUX.md)

## 环境变量说明

配置文件：`backend/.env`（参考 `backend/.env.example`）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | JWT 签发密钥 | `change-this-to-a-random-secret-in-production` |
| `ENCRYPTION_KEY` | Fernet 对称密钥，加密 API Key / 对象存储密钥 | 留空则自动生成 |
| `DATABASE_URL` | MySQL 5.7+/8.0+ 连接串，必须使用 `utf8mb4` | `mysql+pymysql://yibanpaiban:change-me@127.0.0.1:3306/yibanpaiban?charset=utf8mb4` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token 有效期（分钟） | `1440` |
| `DEFAULT_ADMIN_USERNAME` | 首次启动管理员用户名 | `admin` |
| `DEFAULT_ADMIN_PASSWORD` | 首次启动管理员密码 | `admin123` |
| `CORS_ORIGINS` | 允许跨域的前端地址（逗号分隔） | `http://localhost:5173,...` |
| `TRUSTED_PROXY_CIDRS` | 可提供客户端地址的反向代理/CDN CIDR（逗号分隔）；多级代理需包含 Nginx、雷池与 CDN 网段；启动 Uvicorn 时须使用 `--no-proxy-headers` | 留空，不信任转发头 |
| `DOCUMENT_SHARE_IMAGE_URL_EXPIRE_SECONDS` | 只读分享页中对象存储图片签名 URL 的最长有效期（秒） | `3600` |
| `SEARXNG_HOST_PORT` | 本机 SearXNG 容器监听端口，可按部署环境修改 | `8088` |
| `SEARXNG_BASE_URL` | 独立 SearXNG 搜图服务地址；远程实例必须使用 HTTPS | `http://127.0.0.1:8088` |
| `SEARXNG_TIMEOUT_SECONDS` | 单次搜图、候选图片下载与预览请求的超时（秒） | `4` |
| `SEARXNG_SEARCH_CACHE_SECONDS` | 规范化 SearXNG 上游页的短期缓存时间（秒） | `300` |
| `SEARXNG_SECRET` | 与 SearXNG `server.secret_key` 相同的随机值；默认从 `deploy/searxng/.env` 读取 | 必须配置搜图时设置 |

## 搜图服务

编辑器“配图”入口和 Agent 搜图工具使用独立 SearXNG 服务。仓库提供
[`deploy/searxng`](deploy/searxng) 下的单容器配置，服务仅绑定
`127.0.0.1:8088`，不会经过应用 Nginx 暴露到公网。先从示例生成未提交的
`settings.yml` 和随机密钥，将同一密钥写入忽略提交的 `deploy/searxng/.env`，
再执行 `docker compose up -d`；后端和容器会读取同一份密钥。若 8088 冲突，需同时修改
`SEARXNG_HOST_PORT` 和 `SEARXNG_BASE_URL` 中的端口，详细命令见该目录说明。

搜索结果来自互联网，系统不会推断或承诺图片授权。界面会保留来源页并要求使用者在
发布前自行确认版权；应用图片时后端会重新校验图片格式、大小和公网地址并转存到现有
本地/对象存储，不会把搜索引擎外链直接写进文章。

## 对象存储配置

管理员在「文件存储 -> 设置」中选择厂商后，填写 Bucket、AccessKey、Endpoint 和该厂商所需的区域信息。访问密钥仅以加密形式保存，读取配置时只会显示掩码。旧版阿里云 OSS 配置会自动迁移，不需要重新填写密钥。

| 厂商 | Endpoint | 区域 / Zone | 浏览器上传 Endpoint | Bucket 最小权限 |
|------|----------|-------------|---------------------|-----------------|
| 阿里云 OSS | 例如 `oss-cn-hangzhou.aliyuncs.com` | 不需要 | 不需要 | `GetObject`、`PutObject`、`DeleteObject`、`ListObjects` |
| 腾讯云 COS | 例如 `cos.ap-shanghai.myqcloud.com` | 必填，例如 `ap-shanghai` | 不需要 | `GetObject`、`PutObject`、`DeleteObject`、`HeadObject`、`ListBucket` |
| 华为云 OBS | 例如 `obs.cn-north-4.myhuaweicloud.com` | 可选 | 不需要 | 读取、写入、删除、列举对象 |
| 火山引擎 TOS | 例如 `tos-cn-beijing.volces.com` | 必填，例如 `cn-beijing` | 不需要 | `GetObject`、`PutObject`、`DeleteObject`、`HeadObject`、`ListObjects` |
| 七牛云 Kodo | 私有下载域名（推荐自定义域名） | 不需要 | 必填，按存储区域选择，例如 `https://up.qiniup.com` | 上传、下载、删除、列举、获取对象信息 |

所有 Bucket 均应保持私有读。对前端部署域名配置 CORS：阿里云、腾讯云、华为云和火山引擎允许 `PUT`、`GET`、`HEAD`，允许 `Content-Type` 和签名响应要求的请求头，并暴露 `ETag`；七牛云允许 `POST`、`GET`、`HEAD` 及 multipart 表单字段。保存后使用“测试连接”和“测试浏览器直传”分别验证服务器访问权限与浏览器 CORS。七牛云的浏览器上传使用 multipart `POST`，其他四家使用带签名请求头的 `PUT`。

### 未配置 OSS 时

系统自动使用 `backend/data/uploads` 下的本地存储：文档导入、编辑器正文图片、聊天图片、公众号封面、主题参考图和管理员文件管理均可继续上传。管理员文件管理中的通用文件上限为 50MB，并通过限时管理员链接读取；业务文档导入仍只接受 30MB 以内的 PDF、无宏 DOCX 或 UTF-8 Markdown，业务图片仍只接受 10MB 以内、已校验签名和尺寸的 JPG、PNG、GIF、WebP、AVIF 或 BMP。

生产环境必须将 `backend/data/uploads` 挂载到持久化卷。多实例部署需要共享该目录；否则上传文件只能由写入它的实例读取。配置对象存储后，文档导入会恢复为浏览器直传，更适合无状态和多实例部署。

## 使用流程

1. 使用管理员账号登录
2. 在「AI 模型管理」中点击「从预设添加」，选择供应商、填写 API Key 并勾选模型；已添加的 Provider 可点击「获取模型」从供应商接口拉取并批量导入
3. 需要限制模型时，先在「用户组」维护成员，再回到模型的「权限」中选择“仅指定用户和用户组”；管理员始终保留访问权
4. 可直接使用本地存储模式，也可在「存储设置」中配置对象存储并点击“测试浏览器直传”验证。生产部署使用本地存储时，请为 `backend/data/uploads` 配置持久化卷；多实例部署还需要共享该目录。
5. 在「排版工作台」新建空白排版或导入 PDF/Word
6. 进入编辑器，选择模型和「自动 / 开启思考 / 关闭思考」，通过对话描述排版需求
7. 在右侧合规面板查看微信兼容性检测结果
8. 切换到「源码编辑」可手动微调，点击「复制代码」粘贴到公众号编辑器
9. 管理员在「公众号账号」中新增公众号、填写 AppID/AppSecret、将部署服务器公网出口 IP 加入公众号后台 API IP 白名单，并指定可推送的普通用户或用户组
10. 在编辑器点击「推送草稿」，上传封面并完善微信标题、摘要等信息；首次同步会创建草稿，之后默认更新该文章在所选公众号最近一次由本系统成功同步的草稿。需要额外副本时可使用「新建草稿」。符合限制的 JPG/PNG 正文图片会使用微信正文图片接口，其余兼容图片使用永久素材，并替换为微信返回的腾讯域名链接

## 公众号草稿同步

草稿同步仅在服务器端调用微信接口，AppSecret 使用与 AI/对象存储密钥相同的 Fernet 加密机制保存，前端不会获得 AppSecret 或 `access_token`。管理员始终可以向所有已启用账号推送；普通用户只有被直接授权，或属于被授权用户组时，才能看到和使用对应账号。

首次推送会调用微信草稿新增接口；后续默认只更新同一文章、同一公众号最近一次由本系统成功同步且保有 `media_id` 的草稿首篇图文，不会扫描或修改公众号后台的其他草稿。需要额外副本时可明确选择「新建草稿」。系统会记录推送账号、操作者、时间、实际执行的新建或更新、微信 `media_id` 和失败原因。已有草稿记录的账号只能停用，不能直接删除。

同一公众号内，正文图片按原始 URL 和图片内容哈希缓存微信返回的 URL。二次同步命中缓存时不会重新下载或上传图片；微信拒绝旧缓存 URL 时才会对命中的图片重新上传一次并重试写入草稿。

推送前请确认：

- 公众号已开通对应素材与草稿接口权限，部署服务器的公网出口 IP 已加入公众号后台 API IP 白名单。
- 封面为不超过 10 MB 的 JPG、PNG、GIF 或 BMP；封面会作为永久素材上传。
- 正文图片为公网可访问、不超过 10 MB 的 JPG、PNG、GIF 或 BMP。JPG/PNG 不超过 1 MB 时使用微信正文图片接口，其余图片上传为永久素材并替换为微信返回的 URL；透明 PNG 和符合限制的 GIF 均保持原文件。WebP、AVIF、SVG 等不受永久素材接口支持的格式需要先替换。
- 草稿推送由服务器读取图片，不依赖 OSS 对浏览器开放 `GET` 跨域；OSS 仍须允许浏览器直传时所需的 `PUT`、`HEAD` 和请求头。
- 微信标题不超过 32 个字、作者不超过 16 个字、摘要不超过 120 个字。正文内容不在本地按字符数或 HTML 字节数预先拦截，以微信草稿接口实际返回的限制与错误信息为准。

## MySQL 数据库

应用以 MySQL 5.7+ / 8.0+ 为目标数据库。创建库时务必使用 `utf8mb4`，以支持公众号正文、表情和中文：

```sql
CREATE DATABASE yibanpaiban
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

在 `backend/.env` 中填写真实连接串后启动应用。新库会自动创建表；核心大字段的 MySQL 类型如下：

| 数据 | MySQL 类型 | 设计目的 |
|------|------------|----------|
| 文章 `current_html` | `LONGTEXT`（约 4 GiB） | 可保存超长图文 HTML，不受 `TEXT` 64 KiB 限制 |
| 版本内容对象 | `LONGTEXT`（压缩内容） | 版本历史按 SHA-256 去重，通常以增量保存 |
| 聊天正文、工具参数、推理记录 | `LONGTEXT`（约 4 GiB） | 全文替换工具参数可能包含完整 HTML |
| API Key / OSS 密钥密文 | `MEDIUMTEXT`（16 MiB） | 预留足够的加密内容空间 |
| 所有主键与外键 | `BIGINT UNSIGNED` | 支持长期增长的数据量 |

MySQL 的单次通信包也会限制大内容写入。生产库建议将 `max_allowed_packet` 配置为至少 `64M`；文章图片应继续上传 OSS 并引用 URL，不应内联 Base64。

### 从 SQLite 迁移已有数据

目标 MySQL 库必须为空。先备份 `backend/data/app.db`，再在 `backend` 目录执行：

```powershell
$env:SOURCE_SQLITE_URL = 'sqlite:///./data/app.db'
$env:TARGET_DATABASE_URL = 'mysql+pymysql://user:password@127.0.0.1:3306/yibanpaiban?charset=utf8mb4'
python scripts/migrate_sqlite_to_mysql.py
```

脚本会按外键顺序复制用户、模型配置、OSS 配置、文档和聊天记录；发现目标库已有数据会直接终止，不会覆盖。

## 微信合规校验工具

生成或修改排版 HTML 后，可在终端运行：

```bash
# Node.js 版（与逆向源码规则同步）
node wechat_format_rules_source.js path/to/article.html

# Python 版（后端同款引擎）
cd backend
python -m app.services.wechat_compliance path/to/article.html
```

## Agent、流式输出与上下文

编辑器使用 LangGraph 管理 Agent 的状态图：模型通过当前 HTML 的排版块地图工作，使用 `search_html` 定位、`read_blocks` 读取局部源码、`apply_html_patch` 原子修改，只有明确整篇重做时才使用 `replace_document`。补丁使用文档 revision 与块内容 hash 校验，避免模型根据过期行号或旧片段误改；每个文本 token、工具活动和成功编辑后的预览更新都经 SSE 独立事件推送。

上下文不重复携带历史全文 HTML。当前 HTML 工作区和排版块地图是唯一事实来源；当前请求、选中元素和近期两轮原样保留，较早对话先裁剪工具输出，再按模型上下文预算压缩为用户偏好、已完成意图和待办事项。压缩使用同一已授权模型，失败时会安全降级为确定性摘要。每个模型在管理页独立配置最大上下文窗口、实际输入压缩阈值、单次最大输出和单次工具返回上限；阈值与输出必须落在模型总窗口内。切换到更小模型时，编辑器会预判是否需要压缩，压缩后仍无法容纳工作区则禁止发送并提示调整配置。工具目录/搜索结果会在 token 上限内按完整条目裁剪，精确 HTML 超限时会拒绝返回，绝不截成无效标签。

推理模式为单次请求设置：

- Anthropic：开启时映射为 extended thinking（2048 token 预算），关闭时不发送 thinking 参数。
- 已识别的 OpenAI reasoning 模型：映射为 `reasoning_effort`。
- OpenAI Responses API Provider 使用 `/v1/responses`，并将 `reasoning_effort` 映射为 Responses 的 `reasoning.effort`；模型发现仍使用 `/v1/models`。
- Qwen3 / QwQ：映射为 `enable_thinking`。
- 其他 OpenAI 兼容模型：管理员可在「AI 模型管理」的模型编辑中填入 JSON，例如 `{"enabled":{"enable_thinking":true},"disabled":{"enable_thinking":false}}`。未配置且无法识别时，界面会明确提示已回退到自动模式。

模型预设目录以 [models.dev](https://models.dev) 的开源模型能力目录为参考，覆盖 OpenAI、Claude、DeepSeek、通义千问、火山方舟、百度千帆（文心）、Kimi、GLM、硅基流动、OpenRouter、Groq、Together、Grok、Mistral、Perplexity 和 Gemini 的当前主流聊天模型。预设会将支持的“低 / 中 / 高”等思考强度映射为对应供应商参数；不支持或模型固定推理时，编辑器会只展示思考开关或保留自动模式。供应商更新模型后，可在该 Provider 上点击「获取模型」，系统会以已加密保存的 Key 调用其模型列表接口；接口不提供列表时则回退展示内置预设。方舟会返回账号下的推理 Endpoint，并将 `ep-...` Endpoint ID 作为实际调用模型名。

选型时比较了 LangGraph、PydanticAI 和 OpenAI Agents SDK。LangGraph 被采用是因为其图式工具编排、流式事件和后续可加检查点/人工审批节点，且能够保留当前任意 OpenAI 兼容接口与 Anthropic 的 Provider 模型；OpenAI Agents SDK 会把系统更紧地绑定到 OpenAI，PydanticAI 则更适合以类型化工具为中心的较轻量 Agent。

## 项目结构

```
backend/
  app/
    api/          # REST + SSE 路由
    core/         # 配置、JWT、加密
    models/       # SQLAlchemy 模型
    schemas/      # Pydantic 校验
    services/     # 合规引擎、文档解析、OSS、AI Agent
  requirements.txt
frontend/
  src/
    pages/        # 登录、工作台、编辑器、管理页
    components/   # 对话面板、预览、合规面板等
    api/          # 前端 API 封装
wechat_format_rules_source.js   # 微信过滤规则 CLI 工具
rule.prompt.md                  # AI 排版生成规范（系统提示词来源）
```

## 端到端自测清单

- [ ] 管理员登录，修改默认密码
- [ ] 添加 AI Provider 与模型，测试连接成功
- [ ] 配置对象存储并测试连接（导入含图文档时需要）
- [ ] 新建空白排版，进入编辑器
- [ ] 发送对话指令，观察 SSE 流式输出与预览实时刷新
- [ ] 合规面板显示检测结果
- [ ] 源码编辑、保存、复制 HTML
- [ ] 导入 PDF 或 Word 文档，确认图片已替换为对象存储授权链接
- [ ] 普通用户登录，验证只能管理自己的文档

## 技术栈

- 前端：React + TypeScript + Vite + Ant Design
- 后端：Python + FastAPI + SQLAlchemy + MySQL（PyMySQL）
- AI：OpenAI Chat Completions 兼容接口 / OpenAI Responses API / Anthropic Claude（httpx 直连）
- 存储：阿里云 OSS（oss2）、腾讯云 COS、华为云 OBS、火山引擎 TOS、七牛云 Kodo（官方 SDK）
- 文档解析：PyMuPDF（PDF）、python-docx（Word）
