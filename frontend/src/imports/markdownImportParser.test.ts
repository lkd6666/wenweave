import { describe, expect, it } from 'vitest'
import { markdownToSafeHtml } from './markdownImportParser'

describe('markdownToSafeHtml', () => {
  it('converts GFM while removing raw HTML and unsafe links', async () => {
    const html = await markdownToSafeHtml(
      '# 标题\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n<script>alert(1)</script>\n\n[危险](javascript:alert(1))',
    )

    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<table>')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('javascript:')
  })
})
