// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LayoutImitationModal from './LayoutImitationModal'
import { layoutReferencesApi } from '../api/layoutReferences'
import type { LayoutReferencePreview } from '../types'

describe('preparing layout references during a run', () => {
  let root: Root
  let container: HTMLDivElement
  const onConfirm = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    onConfirm.mockClear()
    vi.spyOn(layoutReferencesApi, 'preview').mockResolvedValue({
      reference_id: 'reference-1', canonical_url: 'https://example.test/article',
      title: 'Reference', site_name: 'Example', preview_html: '<p>Reference</p>',
      summary: { extracted_from: 'article', block_count: 1, image_slots: 0, image_assets: 0 },
      assets: [], warning: '', requires_asset_reuse_confirmation: false,
    } satisfies LayoutReferencePreview)
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

  async function render(streaming: boolean) {
    await act(async () => root.render(<LayoutImitationModal
      open streaming={streaming} modelAvailable onClose={vi.fn()} onConfirm={onConfirm}
    />))
  }

  function button(text: string) {
    return Array.from(document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'))
      .find((item) => item.textContent === text)!
  }

  it('allows parsing a reference and keeps application locked until the current run finishes', async () => {
    await render(true)
    const input = document.querySelector<HTMLInputElement>('[placeholder="粘贴公开文章链接（公众号文章优先）"]')!
    expect(input.disabled).toBe(false)
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    await act(async () => {
      valueSetter.call(input, 'https://example.test/article')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(button('解析').disabled).toBe(false)
    await act(async () => button('解析').click())
    expect(layoutReferencesApi.preview).toHaveBeenCalledExactlyOnceWith('https://example.test/article')
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Reference')
    expect(button('确认并开始模仿').disabled).toBe(true)
    await act(async () => button('确认并开始模仿').click())
    expect(onConfirm).not.toHaveBeenCalled()
    await render(false)
    expect(button('确认并开始模仿').disabled).toBe(false)
    await act(async () => button('确认并开始模仿').click())
    expect(onConfirm).toHaveBeenCalledOnce()
  })
})
