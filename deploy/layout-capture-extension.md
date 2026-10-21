# 排版采集助手企业部署

排版采集助手是 Chrome/Edge Manifest V3 扩展，仅在服务端确认微信公众号验证页后启用。扩展不读取微信 Cookie，不接收系统访问令牌；它只保存一次性采集令牌，并使用 `credentials: "omit"` 下载微信图片。

## 构建

开发环境允许 `localhost`：

```powershell
Set-Location frontend
$env:LAYOUT_CAPTURE_APP_ORIGIN = 'http://localhost:5173'
npm run build:layout-capture-extension
```

开发构建会同时允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`，并在扩展启动时为已经打开的应用标签页补充注入桥接脚本。生产构建仍只允许显式配置的单一 HTTPS 来源。

生产构建必须提供不含路径的 HTTPS 系统域名：

```powershell
$env:LAYOUT_CAPTURE_APP_ORIGIN = 'https://example.com'
$env:LAYOUT_CAPTURE_BUILD_MODE = 'production'
npm --prefix frontend run build:layout-capture-extension
```

构建会生成：

- `frontend/extension-dist`：管理员签名和本地验收使用的未打包扩展目录。
- `frontend/public/downloads/layout-capture-extension.zip`：应用内安装教程使用的同源下载包。
- `frontend/public/downloads/layout-capture-extension-<version>.zip`：应用内实际引用的版本化下载包，用于绕过 CDN 旧文件缓存。
- `frontend/public/downloads/layout-capture-extension.json`：前端构建读取的下载文件名、版本和校验值。
- `frontend/public/downloads/layout-capture-extension.zip.sha256`：下载包校验值。

构建结果中的 `manifest.json` 只匹配指定系统域名、`mp.weixin.qq.com` 和微信/QPIC 图片域名。正式发布脚本会先按生产域名构建扩展，再构建网页，确保 ZIP 被复制到 `frontend/dist/downloads`。

## 应用内手动安装

未受企业策略管理的 Chrome/Edge 用户，可在“模仿排版”弹窗检测不到扩展时按内置教程安装：

1. 点击“下载扩展 ZIP”。
2. 解压 ZIP，并确认所选文件夹中可以直接看到 `manifest.json`。
3. 在 Chrome 打开 `chrome://extensions`，或在 Edge 打开 `edge://extensions`。
4. 开启“开发者模式”，点击“加载已解压的扩展程序”或“加载解压缩的扩展”，选择第 2 步的文件夹。
5. 返回应用点击“重新检测”。

发起浏览器抓取后，扩展会打开关联的微信文章标签页，并在页面右上角自动显示采集浮层。浮层会依次显示等待验证、读取正文、处理图片、上传预览和完成/失败状态；用户可以直接在浮层中点击“开始抓取”，浏览器工具栏弹窗保留为备用入口。

从 1.1.3 起，采集优先读取页面初始数据中保存的文章原始 HTML；没有原始数据时，在已验证的文章标签页中读取同源页面源码，失败则使用当前正文 DOM。采集不读取 `getComputedStyle`，按作者 CSS 的选择器优先级、`!important` 与浅色媒体规则保留声明，百分比、CSS 变量和相对尺寸不会转换成当前窗口的像素值。可读取的微信样式表在扩展后台获取并按原顺序处理；背景、遮罩、边框图、SVG 内图片和内嵌位图沿用统一资源本地化流程。页面源码请求沿用文章页的同源浏览器会话，但不读取或回传 Cookie；样式表与图片下载不携带 Cookie。

服务端需同步更新 `backend/app/services/web_article_import.py`、`backend/app/services/layout_reference.py` 和 `backend/app/services/css_declarations.py`，保留正文外层容器、SVG 图片资源与完整浏览器采集结构。采集样式保留大小写敏感的自定义属性和字符串中的分号，不再按单元素截断样式；有样式的空装饰容器保留，同一图片的重复引用按一个资源处理。脚本、事件处理器和外部嵌入仍由服务端过滤；依赖原站脚本的交互不属于静态 HTML 导入，CSS/SVG 动画和外部字体尚未完整保留。

升级手动安装的旧版本时，应先移除旧扩展后重新加载新目录，或用新文件覆盖原目录并在扩展管理页点击“重新加载”。

若开发者模式被组织策略禁用，必须改用下方的企业策略安装方式。

## 发布产物

正式发布时传入系统域名：

```powershell
.\scripts\package-release.ps1 -LayoutCaptureAppOrigin 'https://example.com'
```

发布目录额外包含：

- `layout-capture-extension-<version>/`：管理员签名用的未打包扩展目录，内含 `SHA256SUMS.txt`。
- `layout-capture-extension-enterprise-<version>.zip`：同一目录的企业部署包。
- `layout-capture-extension-enterprise-<version>.zip.sha256`：部署包校验值。

## Chrome/Edge 企业安装

1. 在受保护的构建主机上使用固定私钥打包 CRX。私钥不得放入应用仓库、发布 ZIP 或 Web 服务器目录。
2. 将 CRX 与更新清单托管在企业可访问的 HTTPS 地址。更新清单中的扩展 ID 必须与固定签名私钥一致。
3. Chrome 使用 `ExtensionInstallForcelist` 或 `ExtensionSettings` 配置 `<extension-id>;<update-manifest-url>`。
4. Edge 使用同名 `ExtensionInstallForcelist` 策略配置扩展 ID 与更新清单 URL。
5. 先在受管测试设备检查策略页、扩展版本和系统域名，再逐步扩大强制安装范围。

Chrome/Edge 的“加载已解压的扩展程序”适用于未受管设备的手动安装和本地验收；受管生产设备仍应使用固定签名与企业策略分发。企业升级时必须复用同一受保护私钥，并发布更高的 `manifest.version`。

## 运行边界

- 系统应用必须通过 HTTPS 提供服务；扩展完整接口的反向代理请求体上限至少为 60 MiB。
- 采集会话有效期为 10 分钟且只能完成一次。完成、取消或过期后扩展立即清除 `chrome.storage.session` 中的令牌。
- 图片请求不携带 Cookie，失败、格式不支持、单图超过 10 MiB、超过 200 张或总计超过 50 MiB 的素材会从克隆正文中移除。
- CRX 签名、更新清单发布和企业策略变更应记录管理员、版本、SHA256 和发布时间。
