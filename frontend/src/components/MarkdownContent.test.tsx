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

  it.each(['。', '，', '：', '；', '！', '？', '、', '……', '）', '”'])('renders bold ending with %s before adjacent Chinese text', (punctuation) => {
    const html = renderToStaticMarkup(
      <MarkdownContent content={`前文**需要强调${punctuation}**后续正文`} />,
    )

    expect(html).toContain(`<p>前文<strong>需要强调${punctuation}</strong>后续正文</p>`)
  })

  it.each([false, true])('renders the reported list item with streaming=%s', (streaming) => {
    const html = renderToStaticMarkup(
      <MarkdownContent
        content={'- **但在本项目里，绝对定位要慎用。**这属于经验层面的兼容性约束。'}
        streaming={streaming}
      />,
    )

    expect(html).toContain('<li><strong>但在本项目里，绝对定位要慎用。</strong>这属于经验层面的兼容性约束。</li>')
  })

  it.each([false, true])('renders the reported quotation after adjacent Chinese text with streaming=%s', (streaming) => {
    const html = renderToStaticMarkup(
      <MarkdownContent
        content={'也就是说，限制的是**“绝对定位 + 变形”被用来让视觉顺序偏离 DOM 顺序、让文字脱离自己的背景容器**，并非 `position:absolute` 这个 CSS 属性本身。判断标准只有两条，且必须同时满足：  '}
        streaming={streaming}
      />,
    )

    expect(html).toContain('也就是说，限制的是<strong>“绝对定位 + 变形”被用来让视觉顺序偏离 DOM 顺序、让文字脱离自己的背景容器</strong>，并非 ')
    expect(html).toMatch(/<code(?: [^>]*)?>position:absolute<\/code> 这个 CSS 属性本身。/)
    expect(html).not.toContain('**')
  })

  it('preserves inline formatting inside adjacent bold phrases', () => {
    const html = renderToStaticMarkup(
      <MarkdownContent content={'前文**“慎用 `position:absolute`。”**后文**保留[参考](https://example.test)与*强调*。**结束'} />,
    )

    expect(html).toMatch(/<strong>“慎用 <code(?: [^>]*)?>position:absolute<\/code>。”<\/strong>后文/)
    expect(html).toContain('<strong>保留<a href="https://example.test">参考</a>与<em>强调</em>。</strong>结束')
  })

  it('keeps escaped markers, inline code, and fenced code literal', () => {
    const html = renderToStaticMarkup(
      <MarkdownContent content={'\\*\\*原样。\\*\\*后文\n\n`**代码。**后文`\n\n```text\n**代码块。**后文\n```'} streaming />,
    )

    expect(html).not.toContain('<strong>')
    expect(html).toContain('<p>**原样。**后文</p>')
    expect(html).toMatch(/<code(?: [^>]*)?>\*\*代码。\*\*后文<\/code>/)
    expect(html).toContain('**代码块。**后文')
  })

  it('does not invent closing markers while streaming or enable raw HTML', () => {
    const html = renderToStaticMarkup(
      <MarkdownContent content={'**未完成。\n\n**<img src="x" onerror="alert(1)">。**后文'} streaming />,
    )

    expect(html).toContain('<p>**未完成。</p>')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('<script')
    expect(html).toContain('<strong>&lt;img')
  })

  it('preserves standard English emphasis and punctuation boundaries', () => {
    const html = renderToStaticMarkup(
      <MarkdownContent content={'**Bold.** Next. **normal.**follow and **bold with *italic*.**'} />,
    )

    expect(html).toContain('<strong>Bold.</strong> Next. **normal.**follow and <strong>bold with <em>italic</em>.</strong>')
  })
})
