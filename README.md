# 微信公众号 AI 排版系统

本地可运行的「AI 公众号排版系统」，支持 AI 模型/密钥统一管理、PDF/Word 导入并自动提取图片到阿里云 OSS、类 Claude Code 的多轮对话式 HTML 排版编辑、实时预览、一键复制代码，以及基础用户权限管理。

## 功能概览

- **用户与权限**：管理员 / 普通用户两级角色，支持用户组与按用户/用户组限制模型可用范围，JWT 登录鉴权
- **AI 模型管理**（管理员）：内置主流 Provider/模型预设，自动填写官方 Base URL、协议、思考参数；可加密存储 API Key、拉取模型列表并测试连通性
- **存储设置**（管理员）：配置阿里云 OSS，用于文档导入时图片上传
- **文档导入**：支持 PDF / Word(.docx) 在浏览器本地解析，原文件和图片直传 OSS 后生成排版稿
- **对话式排版**：多轮对话 + 工具调用（局部替换 / 整体重写 / 合规自检），SSE 流式输出
- **Agent 编排**：基于 LangGraph 的 `model -> tools -> model` 图，实时转发 token、工具调用和源码更新
- **排版工作台**：对话面板、实时预览、合规检测面板、源码编辑与复制
- **微信合规引擎**：基于微信编辑器源码逆向分析的规则检测（Python + Node.js 双实现）

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
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
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
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

后端会自动托管 `frontend/dist` 静态文件，访问 http://127.0.0.1:8001 即可使用完整应用。

## 环境变量说明

配置文件：`backend/.env`（参考 `backend/.env.example`）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | JWT 签发密钥 | `change-this-to-a-random-secret-in-production` |
| `ENCRYPTION_KEY` | Fernet 对称密钥，加密 API Key / OSS 密钥 | 留空则自动生成 |
| `DATABASE_URL` | MySQL 5.7+/8.0+ 连接串，必须使用 `utf8mb4` | `mysql+pymysql://yibanpaiban:change-me@127.0.0.1:3306/yibanpaiban?charset=utf8mb4` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token 有效期（分钟） | `1440` |
| `DEFAULT_ADMIN_USERNAME` | 首次启动管理员用户名 | `admin` |
| `DEFAULT_ADMIN_PASSWORD` | 首次启动管理员密码 | `admin123` |
| `CORS_ORIGINS` | 允许跨域的前端地址（逗号分隔） | `http://localhost:5173,...` |

## 使用流程

1. 使用管理员账号登录
2. 在「AI 模型管理」中点击「从预设添加」，选择供应商、填写 API Key 并勾选模型；已添加的 Provider 可点击「获取模型」从供应商接口拉取并批量导入
3. 需要限制模型时，先在「用户组」维护成员，再回到模型的「权限」中选择“仅指定用户和用户组”；管理员始终保留访问权
4. （如需导入含图文档）在「存储设置」中配置阿里云 OSS；在 OSS 控制台为前端域名配置 CORS，允许 `PUT`、`GET`、`HEAD`，允许 `Content-Type` 与 `x-oss-*` 请求头并暴露 `ETag`，然后点击“测试浏览器直传”验证
5. 在「排版工作台」新建空白排版或导入 PDF/Word
6. 进入编辑器，选择模型和「自动 / 开启思考 / 关闭思考」，通过对话描述排版需求
7. 在右侧合规面板查看微信兼容性检测结果
8. 切换到「源码编辑」可手动微调，点击「复制代码」粘贴到公众号编辑器

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
- [ ] 配置 OSS 存储并测试连接（导入含图文档时需要）
- [ ] 新建空白排版，进入编辑器
- [ ] 发送对话指令，观察 SSE 流式输出与预览实时刷新
- [ ] 合规面板显示检测结果
- [ ] 源码编辑、保存、复制 HTML
- [ ] 导入 PDF 或 Word 文档，确认图片已替换为 OSS 链接
- [ ] 普通用户登录，验证只能管理自己的文档

## 技术栈

- 前端：React + TypeScript + Vite + Ant Design
- 后端：Python + FastAPI + SQLAlchemy + MySQL（PyMySQL）
- AI：OpenAI 兼容接口 / Anthropic Claude（httpx 直连）
- 存储：阿里云 OSS（oss2 SDK）
- 文档解析：PyMuPDF（PDF）、python-docx（Word）
