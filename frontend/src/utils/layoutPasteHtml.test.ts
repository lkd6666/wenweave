// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import { plainTextLayoutHtml, sanitizeLayoutPasteHtml } from './layoutPasteHtml'

describe('layout clipboard HTML', () => {
  it('preserves inline typography, alignment, spacing and external image sources for later transfer', () => {
    const html = sanitizeLayoutPasteHtml('<section style="padding:24px;color:#287d68"><h2 style="text-align:center">标题</h2><p><strong>正文</strong></p><img data-src="https://example.test/photo.png"><div style="background:url(https://example.test/bg.png)">背景</div></section>')
    expect(html).toContain('padding:24px;color:#287d68')
    expect(html).toContain('text-align:center')
    expect(html).toContain('<strong>正文</strong>')
    expect(html).toContain('data-src="https://example.test/photo.png"')
    expect(html).toContain('background:url(https://example.test/bg.png)')
  })

  it('removes active documents, executable attributes and unsafe resource protocols', () => {
    const html = sanitizeLayoutPasteHtml('<meta http-equiv="refresh" content="0;url=https://evil.test"><base href="https://evil.test"><style>body{color:red}</style><script>alert(1)</script><iframe src="https://evil.test"></iframe><form><input></form><p onclick="evil()" contenteditable="false">正文</p><a href="java\tscript:evil()">链接</a><img src="file:///secret" onerror="evil()"><img srcset="https://evil.test 2x"><svg><foreignObject><p>hidden</p></foreignObject><use href="javascript:evil()"></use></svg>')
    for (const value of ['<script', '<iframe', '<style', '<meta', '<base', '<form', '<input', 'onclick', 'onerror', 'contenteditable', 'srcset', 'javascript', 'file://', 'foreignObject', 'evil.test']) {
      expect(html).not.toContain(value)
    }
    expect(html).toContain('正文')
    expect(html).toContain('链接')
  })

  it('keeps safe raster data images and SVG shapes while stripping data HTML and SVG documents', () => {
    const html = sanitizeLayoutPasteHtml('<img src="data:image/png;base64,AAAA"><img src="data:text/html,evil"><img src="data:image/svg+xml,evil"><svg viewBox="0 0 20 20"><rect width="20" fill="#287d68"></rect></svg>')
    expect(html).toContain('data:image/png;base64,AAAA')
    expect(html).not.toContain('data:text/html')
    expect(html).not.toContain('data:image/svg+xml')
    expect(html).toContain('viewBox="0 0 20 20"')
    expect(html).toContain('<rect')
  })

  it('escapes plaintext and preserves line breaks and literal markup', () => {
    expect(plainTextLayoutHtml('标题\r\n\r\n<script>只是文字</script> & 正文')).toBe('<p>标题</p><p><br></p><p>&lt;script&gt;只是文字&lt;/script&gt; &amp; 正文</p>')
  })
})
