// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CollapsibleMessage from './CollapsibleMessage'

describe('sent message folding', () => {
  let container: HTMLDivElement
  let root: Root
  let height: number
  let resize: () => void

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    height = 480
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() => height)
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resize = callback }
      observe() {}
      disconnect() {}
    })
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it.each(['长消息'.repeat(1000), Array.from({ length: 40 }, (_, i) => `第 ${i + 1} 行`).join('\n')])(
    'keeps the complete text and toggles its visible height', async (text) => {
      await act(async () => root.render(<CollapsibleMessage>{text}</CollapsibleMessage>))
      const viewport = container.querySelector<HTMLElement>('.collapsible-message-viewport')!
      const button = container.querySelector('button')!
      expect(viewport.textContent).toBe(text)
      expect(viewport.style.maxHeight).toBe('240px')
      expect(button.getAttribute('aria-expanded')).toBe('false')
      await act(async () => button.click())
      expect(viewport.style.maxHeight).toBe('')
      expect(button.textContent).toBe('收起')
      await act(async () => button.click())
      expect(viewport.style.maxHeight).toBe('240px')
      expect(viewport.textContent).toBe(text)
    },
  )

  it('does not fold short messages and measures image loading and responsive changes', async () => {
    height = 100
    await act(async () => root.render(<CollapsibleMessage><span>查看这些图片</span><img src="/photos/first.png" /></CollapsibleMessage>))
    expect(container.querySelector('button')).toBeNull()
    height = 600
    await act(async () => resize())
    expect(container.querySelector('button')?.textContent).toBe('展开全文')
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/photos/first.png')
    height = 180
    await act(async () => resize())
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector<HTMLElement>('.collapsible-message-viewport')?.style.maxHeight).toBe('')
  })
})
