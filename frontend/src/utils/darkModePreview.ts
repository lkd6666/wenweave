import mpDarkmodeScript from 'mp-darkmode/dist/darkmode.min.js?raw'
import { ARTICLE_RENDER_CSS, ARTICLE_RENDER_ROOT_CLASS, ARTICLE_RENDER_VIEWPORT } from './articleFrame'
import { articleHtmlWithNewWindowLinks } from './frameLinks'

export const DARK_MODE_PREVIEW_HEIGHT_MESSAGE = 'yiban-preview-dark-mode-height'
/**
 * This frame must retain its opaque sandboxed origin. In particular, do not
 * add `allow-same-origin`: article markup is intentionally untrusted even
 * though the conversion script itself is bundled by the application.
 */
export const DARK_MODE_PREVIEW_SANDBOX = 'allow-scripts allow-popups allow-popups-to-escape-sandbox'

export interface DarkModePreviewHeightMessage {
  type: typeof DARK_MODE_PREVIEW_HEIGHT_MESSAGE
  token: string
  height: number
}

export interface DarkModePreviewDocumentOptions {
  html: string
  token: string
}

function escapeInlineScript(source: string): string {
  return source.replace(/<\/script/gi, '<\\/script')
}

function contentSecurityPolicy(nonce: string): string {
  return [
    "default-src 'none'",
    "base-uri 'none'",
    `script-src 'nonce-${nonce}'`,
    "style-src 'unsafe-inline'",
    'img-src http: https: data: blob:',
    'media-src http: https: data: blob:',
    'font-src http: https: data: blob:',
    "connect-src 'none'",
    "object-src 'none'",
    "frame-src 'none'",
  ].join('; ')
}

/**
 * Builds the opaque, read-only frame used to inspect an article with the same
 * conversion library as WeChat's Dark Mode checker. The article itself stays
 * in the editor's same-origin iframe, so conversion classes and generated CSS
 * can never become part of a saved draft.
 */
export function buildDarkModePreviewDocument({ html, token }: DarkModePreviewDocumentOptions): string {
  const nonce = token
  const articleHtml = articleHtmlWithNewWindowLinks(html)
  const safeDarkmodeScript = escapeInlineScript(mpDarkmodeScript)
  const runner = `
(() => {
  const token = ${JSON.stringify(token)};
  const messageType = ${JSON.stringify(DARK_MODE_PREVIEW_HEIGHT_MESSAGE)};
  const reportHeight = () => {
    const body = document.body;
    const root = document.documentElement;
    if (!body || !root) return;
    const height = Math.ceil(Math.max(
      160,
      body.scrollHeight,
      root.scrollHeight,
      body.getBoundingClientRect().height,
    ));
    parent.postMessage({ type: messageType, token, height }, '*');
  };
  const applyDarkMode = () => {
    try {
      const nodes = Array.from(document.body.querySelectorAll('*'));
      if (window.Darkmode && typeof window.Darkmode.run === 'function') {
        window.Darkmode.run(nodes, {
          mode: 'dark',
          defaultDarkTextColor: '#989898',
          defaultDarkBgColor: '#191919',
          whitelist: { attribute: ['data-no-dark'] },
          needJudgeFirstPage: false,
        });
      }
    } finally {
      requestAnimationFrame(reportHeight);
      window.setTimeout(reportHeight, 0);
    }
  };
  document.addEventListener('DOMContentLoaded', () => {
    applyDarkMode();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(reportHeight);
    observer?.observe(document.body);
    window.addEventListener('load', reportHeight, { once: true });
    document.fonts?.ready?.then(reportHeight).catch(() => undefined);
  }, { once: true });
})();`

  // Do not pass this complete document through DOMParser. Real browsers hide
  // nonce attributes when serializing a DOM, which would cause CSP to block
  // both bundled converter scripts. Links were normalized in articleHtml.
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="${ARTICLE_RENDER_VIEWPORT}" />
  <meta name="referrer" content="no-referrer" />
  <meta http-equiv="Content-Security-Policy" content="${contentSecurityPolicy(nonce)}" />
  <style nonce="${nonce}">
    html, body {
      width: 100%;
      min-height: 100%;
      margin: 0;
      box-sizing: border-box;
      overflow: hidden;
      background: #191919;
    }
    ${ARTICLE_RENDER_CSS}
    body.${ARTICLE_RENDER_ROOT_CLASS} {
      background: #191919;
      color: #989898;
    }
  </style>
  <script nonce="${nonce}">${safeDarkmodeScript}</script>
  <script nonce="${nonce}">${escapeInlineScript(runner)}</script>
</head>
<body class="${ARTICLE_RENDER_ROOT_CLASS}">${articleHtml}</body>
</html>`
}

export function isDarkModePreviewHeightMessage(value: unknown): value is DarkModePreviewHeightMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<DarkModePreviewHeightMessage>
  return candidate.type === DARK_MODE_PREVIEW_HEIGHT_MESSAGE
    && typeof candidate.token === 'string'
    && typeof candidate.height === 'number'
    && Number.isFinite(candidate.height)
}
