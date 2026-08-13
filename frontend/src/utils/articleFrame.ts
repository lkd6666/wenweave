export const ARTICLE_RENDER_ROOT_CLASS = 'yiban-article-render-root'

export const ARTICLE_RENDER_VIEWPORT = 'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no'

/** The single rendering baseline used by both the editor canvas and read-only shares. */
export const ARTICLE_RENDER_CSS = `
.${ARTICLE_RENDER_ROOT_CLASS} {
  width: 100%;
  box-sizing: border-box;
  overflow: hidden;
  margin: 0;
  padding: 16px 12px 32px;
  background: #fff;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 15px;
  line-height: 2;
  color: #000;
  word-wrap: break-word;
}
.${ARTICLE_RENDER_ROOT_CLASS} table { max-width: 100%; }
`
