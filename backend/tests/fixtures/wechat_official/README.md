# Official regression fixtures

`good-responsive.html`, `good-line-height-single-line.html`, and
`bad-official-violations.html` are the corresponding compact fixtures from the
official `verify-article-structure-spec` CLI suite at commit
`fa69e37341c86bfec4c8c533845910511e534c0c`. The remaining files exercise
official Dark Mode and exemption behavior. They run only with
`RUN_WECHAT_BROWSER_TESTS=1`, after installing Playwright Chromium.

The expected rule keys are asserted against the vendored official browser
bundle, not a local reimplementation.
