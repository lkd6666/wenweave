import { frameDocumentWithNewWindowLinks } from './frameLinks'

export function frameThemeDocument(html: string, display: 'thumbnail' | 'full' = 'thumbnail') {
  const bodyStyle = display === 'full'
    ? 'html,body{margin:0;min-height:100%;background:#f3f5f7}body{padding:24px 16px;box-sizing:border-box}img{max-width:100%;height:auto}'
    : 'html,body{margin:0;background:#fff;overflow:hidden}body{padding:0;box-sizing:border-box}img{max-width:100%;height:auto}'
  return frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: https: http:" />
<style>${bodyStyle}</style>
</head><body>${html}</body></html>`)
}
