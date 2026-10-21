# 一版排版前端

基于 React、TypeScript、Vite 和 Ant Design 的公众号排版工作台，包含文章编辑器、聊天与源码工具展示、图片和模板库、管理后台，以及 Chrome / Edge 排版采集助手。

系统功能、数据库与后端启动步骤见[项目 README](../README.md)。

## 本地开发

需要 Node.js 20.19+ 或 22.12+。在 `frontend` 目录执行：

```powershell
npm ci
npm run dev
```

默认开发地址为 `http://localhost:5173`，`/api` 代理到 `http://127.0.0.1:8002`。后端按根目录说明启动；需要自定义端口时，在启动 Vite 前设置进程环境变量：

```powershell
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:8003'
npm run dev
```

macOS / Linux 可使用 `VITE_API_PROXY_TARGET=http://127.0.0.1:8003 npm run dev`。这项设置只影响开发代理。

## 检查与构建

| 命令 | 用途 |
| --- | --- |
| `npm run lint` | 使用 Oxlint 检查代码 |
| `npm run test` | 使用 Vitest 运行前端与扩展测试 |
| `npm run build:layout-capture-extension` | 对扩展做 TypeScript 检查并构建安装包 |
| `npm run build` | TypeScript 项目检查和 Vite 生产构建 |
| `npm run preview` | 本地预览已构建的网页静态资源 |

单独运行测试文件可使用 `npm run test -- src/utils/imageUpload.test.ts`。`npm run preview` 仅用于查看构建产物，完整接口联调使用开发代理或后端静态资源托管。

## 采集助手

本地开发默认允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`：

```powershell
npm run build:layout-capture-extension
```

生产发布时，先用实际系统的 HTTPS 来源构建扩展，再构建网页，以便 Vite 将下载包和版本元数据复制进 `dist/downloads/`：

```powershell
$env:LAYOUT_CAPTURE_APP_ORIGIN = 'https://example.com'
$env:LAYOUT_CAPTURE_BUILD_MODE = 'production'
npm run build:layout-capture-extension
npm run build
```

扩展输出到 `extension-dist/`，同源下载包和元数据输出到 `public/downloads/`；这些都是被 Git 忽略的构建产物。安装、升级、权限与企业分发见[扩展部署说明](../deploy/layout-capture-extension.md)。正式发布可直接使用根目录的 `scripts/package-release.ps1` 完成上述构建流程。

## 代码布局

```text
src/api/          后端请求、鉴权续期、聊天 SSE 与素材接口
src/components/   聊天、预览、图片、模板与用户提问组件
src/hooks/        上传进度等共享交互逻辑
src/pages/        工作台、编辑器与管理员页面
src/utils/        选区、上传、SVG 图层、深色预览与连接恢复
src/store/        客户端状态
extension/src/    应用桥接、微信正文和作者样式采集、资源下载
```

测试通常与实现同目录，使用 `*.test.ts` / `*.test.tsx` 命名。修改 Agent 事件或图片协议时，应同时检查 `src/types.ts`、`src/api/` 和后端 schema；源码工具、上下文压缩与提示缓存设计见根 README 的文档导航。
