# 贡献指南

感谢你对一版排版（YiBanPaiBan）的关注与贡献。

## 开始前

1. 先阅读根目录的 [README](README.md)，按其中的步骤准备 Python、Node.js 与 MySQL 开发环境。
2. 在实现较大的功能或行为变更前，请先通过 Issue 说明目标、影响范围和预期方案。
3. 每项修改使用一个聚焦的分支；建议使用 `feat/<topic>`、`fix/<topic>` 或 `docs/<topic>` 等命名。

## 提交 Pull Request

- 保持 PR 小而聚焦，说明问题、解决方案、用户可见的变化和验证结果。
- 为新增或修复的行为补充相应测试；不要顺带格式化或重构无关文件。
- 提交前运行与修改范围相关的检查：

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

- PR 描述应说明未运行的检查及其原因。维护者可能要求补充测试、文档或拆分无关改动。

## 安全与隐私

绝不要提交或公开以下内容：

- `.env`、API Key、对象存储凭据、公众号 AppSecret、JWT 密钥或加密密钥；
- 数据库备份、`backend/data/`、上传的用户文件、真实用户数据或日志；
- `tmp/`、`debug-artifacts/` 等临时抓取、调试和性能分析产物。

提交前请执行 `git status --short`，并检查新增文件、截图和日志不含敏感信息。安全问题请避免在公开 Issue 中披露可利用细节，并联系项目维护者进行私下协调。

## 许可证

提交贡献即表示你有权提交该代码，并同意将贡献以 [AGPL-3.0-or-later](LICENSE) 许可证提供。请保留现有的版权、许可证和第三方声明；涉及 `_third_party/` 内容时，必须同时遵守上游许可证与署名要求。
