// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import PromptComposer from './PromptComposer'

it('uploads a large clipboard payload without inserting its text or HTML into the composer', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const onChange = vi.fn(), onPasteText = vi.fn()
  const text = 'PRIVATE_PASTED_TEXT_'.repeat(2000)
  try {
    await act(async () => root.render(<PromptComposer value="short instruction" references={[]} templates={[]}
      onChange={onChange} onPasteText={onPasteText} onSubmit={vi.fn()} onRemoveReference={vi.fn()}
      onDuplicateReference={vi.fn()} onMoveReference={vi.fn()} onRemoveTemplate={vi.fn()} />))
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { items: [], getData: (type: string) => type === 'text/plain' ? text : '<script>evil()</script>' } })
    await act(async () => { container.querySelector('[role="textbox"]')!.dispatchEvent(event) })
    expect(event.defaultPrevented).toBe(true)
    expect(onPasteText).toHaveBeenCalledExactlyOnceWith(text)
    expect(onChange).not.toHaveBeenCalled()
    expect(container.textContent).not.toContain('PRIVATE_PASTED_TEXT_')
    expect(container.querySelector('script')).toBeNull()
  } finally { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals() }
})
