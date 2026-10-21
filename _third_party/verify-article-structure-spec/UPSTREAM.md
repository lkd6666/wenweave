# Upstream snapshot

This directory vendors the WeChat official article-structure specification
from <https://github.com/wechatjs/verify-article-structure-spec>.

- Fixed upstream commit: `fa69e37341c86bfec4c8c533845910511e534c0c`
- Browser checker package: `@tencent/verify-article-structure` v0.2.16
- License: MIT; see `LICENSE`.
- Bundled Dark Mode dependency: `mp-darkmode` v1.2.3-alpha.1, MIT; see
  `MP_DARKMODE_LICENSE`.

Vendored source consists of the official specification, the CLI engine
TypeScript source, and the prebuilt browser bundle at
`cli/dist/verify-article-structure.browser.js`. The bundle was generated from
this exact source with `npm run build:browser` in the upstream `cli` directory.
Its SHA-256 is:

```text
91b47add05f526a3eedd35d25b4ae2f89df0ebc80e0e1e6100f00f686875f9f
```

Production code loads only the checked-in browser bundle through Python
Playwright. It neither installs nor executes Node.js, and it never fetches or
updates this snapshot at runtime. Any upgrade must explicitly update this
snapshot, its bundle hash, tests, version metadata, and third-party notice.
