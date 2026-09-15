// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CodeBlock from './CodeBlock'
import MarkdownContent from './MarkdownContent'

const highlight = vi.hoisted(() => vi.fn())
vi.mock('./SyntaxHighlightedCode', () => ({
  default: ({ code }: { code: string }) => {
    highlight(code)
    return <pre data-highlighted><code>{code}</code></pre>
  },
}))

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  highlight.mockClear()
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('code rendering budgets', () => {
  it('keeps live Markdown formatted without repeatedly highlighting growing code', async () => {
    for (let count = 1; count <= 5; count += 1) {
      const code = '<p>完整正文</p>\n'.repeat(count)
      await act(async () => root.render(<MarkdownContent content={'**说明**\n\n```html\n' + code} streaming />))
      expect(container.querySelector('strong')?.textContent).toBe('说明')
      expect(container.querySelector('pre')?.textContent).toBe(code.trimEnd())
    }
    expect(highlight).not.toHaveBeenCalled()
    await act(async () => root.render(<MarkdownContent content={'**说明**\n\n```html\n<p>最终正文</p>\n```'} />))
    expect(highlight).toHaveBeenCalled()
    expect(container.querySelector('[data-highlighted]')?.textContent).toBe('<p>最终正文</p>')
  })

  it('renders and copies all of a large code block without tokenizing it', async () => {
    const code = '<p>很长的源码</p>\n'.repeat(4000)
    const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    await act(async () => root.render(<CodeBlock code={code} language="html" />))
    expect(highlight).not.toHaveBeenCalled()
    expect(container.querySelector('pre')?.textContent).toBe(code)
    await act(async () => container.querySelector<HTMLButtonElement>('button')?.click())
    expect(copy).toHaveBeenCalledWith(code)
    copy.mockRestore()
  })
})
