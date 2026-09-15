# 一版排版（YiBanPaiBan）

面向微信公众号创作者的本地可部署 AI 排版系统。它将文档与文章链接导入、对话式 HTML 编辑、实时预览、微信兼容性检查、配图、主题模板和公众号草稿同步整合到一个工作台中；AI 模型、密钥与用户权限均由部署者自行管理。

> 本项目可自行部署，不提供或代管任何第三方 AI、对象存储或微信公众号账号。

## 核心能力

- **对话式公众号排版**：基于 LangGraph 的多轮 Agent，可局部修改或重写文章 HTML，并通过 SSE 实时显示输出、工具调用和预览更新。
- **导入、预览与合规检查**：支持 PDF、DOCX、Markdown 和公开 HTTPS 文章链接导入；在浏览器中编辑、预览、复制可直接粘贴到公众号编辑器的富文本文章。模型调用与任务结束时通过微信官方 `verify-article-structure-spec` 浏览器规则包检查 CSS、布局、结构、字体和 Dark Mode。
- **模型与权限管理**：管理员可配置 OpenAI 兼容接口、OpenAI Responses API、Anthropic Claude 或 Google Gemini 原生 API，按用户和用户组控制模型可用范围；密钥加密保存。
- **素材与配图**：支持本地存储或阿里云 OSS、腾讯云 COS、华为云 OBS、火山引擎 TOS、七牛云 Kodo；可选 SearXNG 搜图和 AI 生图（OpenAI Images、阿里百炼文生图、火山方舟图片协议）。
- **公众号草稿同步**：可管理多个公众号账号、授权可推送用户，并创建或更新草稿；AppSecret 仅在服务端加密保存。
- **模板、主题与版本历史**：提供组件模板库、整篇主题库、主题生成与确认流程，以及内容寻址的增量版本历史。
- **参考排版与分享**：可读取公开文章作为只读排版参考，生成限时公开的只读分享链接，并管理有效期、撤销和访客记录。
- **工作看板与管理后台**：工作看板汇总模型调用、用户调用和推文创作活动；管理员后台提供品牌、图片库、正文排版、公众号账号、用户、用户组和操作日志设置。

## 界面预览

以下为项目主要功能页面截图。

### 工作台

![推文工作台](docs/images/workbench.png)

### AI 排版编辑器

![AI 排版编辑器](docs/images/editor.png)

### 图片库与搜图

![图片库与搜图](docs/images/image-library.png)

### 公众号草稿同步

![公众号草稿同步](docs/images/wechat-draft.png)

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | React、TypeScript、Vite、Ant Design |
| 后端 | Python 3.11+、FastAPI、SQLAlchemy、MySQL |
| AI 编排 | LangGraph、OpenAI 兼容接口 / Responses API、Anthropic Claude、Google Gemini 原生 API |
| 文档与存储 | PyMuPDF、python-docx、对象存储厂商 SDK |

```text
浏览器（React + Vite）
        │ /api
        ▼
FastAPI（鉴权、Agent、文档、同步、SSE）
   ├── MySQL（用户、配置、文章、会话、版本）
   ├── 本地存储或对象存储（文件与图片）
   ├── 已配置的 AI Provider
   └── 可选：SearXNG、微信公众号接口
```

## 快速开始

### 环境要求

- Python 3.11 或更高版本
- Node.js 20.19+ 或 22.12+（仅前端开发/构建需要；生产运行不需要 Node.js）
- Chromium（Python Playwright 用于官方微信合规检测）
- MySQL 5.7 或 8.0，数据库字符集必须为 `utf8mb4`（正式部署必需；SQLite 仅用于本地实验和测试）
- 可选：Docker Compose（运行 SearXNG 搜图服务）

### 1. 创建数据库

使用有建库权限的 MySQL 账号创建数据库，并按实际账号密码修改后端环境变量：

```sql
CREATE DATABASE yibanpaiban
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

### 2. 启动后端

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

在 `backend/.env` 中至少填写真实的 `DATABASE_URL`。开发环境可让 `ENCRYPTION_KEY` 留空，应用会在首次启动时生成本地密钥；生产环境必须显式配置强随机的 `SECRET_KEY` 和 `ENCRYPTION_KEY`。

```powershell
# 开发环境必须使用 8002，与前端 Vite 的默认代理一致
python -m app.dev_server --host 127.0.0.1 --port 8002
```

macOS / Linux 激活虚拟环境时使用 `source venv/bin/activate`，复制配置文件时使用 `cp .env.example .env`。
如果将后端改用其他端口，请在启动前端前设置进程环境变量 `VITE_API_PROXY_TARGET`，使 Vite 代理指向相同地址（PowerShell 使用 `$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:端口'`，macOS/Linux 使用 `VITE_API_PROXY_TARGET=http://127.0.0.1:端口 npm run dev`）。

后端启动时会自动创建缺失的数据表并执行兼容性 schema migration；已有数据库请先完成备份。
官方合规 Chromium 在首次模型检测时才启动，并由进程复用；编辑、保存和同步草稿不会自动发起检测，编辑后只会使上次报告失效。

### 3. 启动前端

```powershell
cd frontend
npm ci
npm run dev
```

访问 <http://localhost:5173>。开发环境首次初始化且用户表为空时，会创建默认管理员账号 `admin` / `admin123`；请在首次登录后立即修改密码。生产环境必须在 `.env` 中设置自定义管理员账号和密码，不能使用这组默认凭据。

### 4. 完成初始配置

1. 使用管理员账号登录，在“AI 模型管理”中按需添加可用 Provider 和模型；未配置 Provider 时仍可导入、手动编辑和预览，但 AI 对话与 AI 生图不可用。
2. 按需在“文件存储”配置对象存储；未配置时系统使用 `backend/data/uploads` 本地存储。
3. 在“排版工作台”新建文章或导入文档，选择模型后开始对话式排版。

API Key、对象存储凭据、AppSecret、`.env`、数据库和 `backend/data/` 都是私密数据，不得提交到仓库或公开发布。

## 可选服务与生产部署

- **图片搜索**：编辑器搜图功能使用独立的 SearXNG 服务。配置与国内来源验证步骤见 [SearXNG 部署说明](deploy/searxng/README.md)。未启动时仅搜图不可用，其他功能仍可使用。
- **对象存储**：可通过管理界面配置；本地存储模式在生产环境必须将 `backend/data/uploads` 挂载到持久化卷。
- **公众号草稿同步**：需要公众号具备相应接口权限，并将部署服务器公网出口 IP 加入公众号后台 API IP 白名单。
- **文章链接导入与模仿排版**：普通公开 HTTPS 文章可直接解析；微信公众号页面在服务端验证失败时，需要 Chrome/Edge 排版采集助手。构建与安装见[排版采集助手部署说明](deploy/layout-capture-extension.md)。
- **生产环境**：生产服务默认监听 `127.0.0.1:8001`，建议在 Nginx 后运行。详见[常规 Linux 部署](docs/DEPLOY_LINUX.md)或[宝塔面板部署](docs/DEPLOY_BAOTA.md)。
- **发布包**：可使用 [`scripts/package-release.ps1`](scripts/package-release.ps1) 构建包含前端静态资源、MySQL schema 和采集扩展的发布包；脚本要求工作区干净，并需要传入生产 HTTPS 来源。

完整配置项及默认值请参阅 [后端环境变量示例](backend/.env.example)。

## 开发与测试

```powershell
# 后端
cd backend
python -m unittest discover -s tests

# 前端
cd frontend
npm run lint
npm run test
npm run build
```

提交或发布前，请使用 `git status --short` 确认未暂存 `.env`、数据库、上传文件，以及 `tmp/`、`debug-artifacts/` 等本地或调试产物。

## 贡献

欢迎通过 Issue 反馈问题，并以 Pull Request 提交改进。提交前请阅读[贡献指南](CONTRIBUTING.md)，并确保相关检查通过。请不要在 Issue、日志、截图或提交记录中泄露访问令牌、用户数据、公众号凭据或其他敏感信息。

## 第三方组件、合规与免责声明

- 本项目集成了 `gzh-design-skill` 的源码快照，用于主题组件和 HTML 校验；其版权声明与 AGPL 许可证保留在原目录。其他第三方来源与分发注意事项见 [第三方声明](THIRD_PARTY_NOTICES.md)。
- 第三方声明还记录了 AI 输出界面采用的 AICSS 示例代码；其公开许可证或条款在本声明编写时尚未确认，正式分发前请完成许可审查、取得授权或替换相关实现。
- 本项目与微信、腾讯、OpenAI、Anthropic 及其他模型、存储或搜索服务商均无官方隶属或授权关系。
- 部署者与内容发布者须自行遵守适用法律、微信公众号平台规则、第三方服务条款及图片、文字、商标等内容的授权要求。

## 许可证

本项目以 [GNU Affero General Public License v3.0 or later](LICENSE)（`AGPL-3.0-or-later`）发布。由于项目包含并集成 AGPL 第三方组件，通过网络向用户提供本项目服务时，请履行 AGPL 对对应源码提供的义务。

## 赞赏

如果一版排版对你有所帮助，欢迎赞赏支持项目持续维护与改进。

![赞赏码](docs/images/reward.png)
