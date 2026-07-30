import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import MarkdownContent, { normalizeMathMarkdown } from './MarkdownContent'

describe('MarkdownContent', () => {
  it('renders standard and legacy LaTex notation as KaTeX', () => {
    const html = renderToStaticMarkup(
      <MarkdownContent content={'输入电阻 (R_1=10k\\Omega)\n\n[ A_v=(-2)\\times(-2)=+4 ]'} />,
    )

    expect(html).toContain('katex')
    expect(html).toContain('katex-display')
    expect(html).toContain('×')
  })

  it('does not reinterpret code samples as formulas', () => {
    const source = '`(R_1=10k\\Omega)`\n\n```text\n[ A_v=(-2)\\times(-2)=+4 ]\n```'

    expect(normalizeMathMarkdown(source)).toBe(source)
  })
})
