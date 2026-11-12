# Upstream snapshot

This directory vendors the WeChat official article-structure specification
from <https://github.com/wechatjs/verify-article-structure-spec>.

- Fixed upstream commit: `4a3daa63774df71683f41587b4f0b8009e9cb33f`
- Browser checker package: `verify-article-structure` v0.2.28
- License: MIT; see `LICENSE`.
- Bundled Dark Mode dependency: `mp-darkmode` v1.2.3-alpha.6, MIT; see
  `MP_DARKMODE_LICENSE`.

Vendored source consists of the official specification, the CLI engine
TypeScript source, its build manifest/lockfile, and the prebuilt browser bundle at
`cli/dist/verify-article-structure.browser.js`. The bundle was generated from
this exact source with `npm install --ignore-scripts --package-lock=false` and
`npm run build:browser` in the upstream `cli` directory.
Its SHA-256 is:

```text
37523afb3d9d7ce51dc2c082f53c6f896fc3974e8a813db6ce5b8910b314e107
```

Production code loads only the checked-in browser bundle through Python
Playwright. It neither installs nor executes Node.js, and it never fetches or
updates this snapshot at runtime. Any upgrade must explicitly update this
snapshot, its bundle hash, tests, version metadata, and third-party notice.
