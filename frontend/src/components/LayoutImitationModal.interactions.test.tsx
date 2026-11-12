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
  it.each([false, true])('displays rich clipboard HTML without duplicating an insertion (command changes DOM but returns false: %s)', async (commandChangesDom) => {
    const paste = vi.spyOn(layoutReferencesApi, 'paste').mockResolvedValue({
      reference_id: 'pasted', canonical_url: '', title: 'Pasted', site_name: '粘贴内容', preview_html: '<p>正文</p>',
      summary: { extracted_from: '粘贴的 HTML', block_count: 1, image_slots: 0, image_assets: 0 },
      assets: [], warning: '', requires_asset_reuse_confirmation: false,
    })
    await render(false)
    await act(async () => Array.from(document.querySelectorAll('label.ant-segmented-item')).find(item => item.textContent === '粘贴原文')!.querySelector<HTMLInputElement>('input')!.click())
    const frame = document.querySelector<HTMLIFrameElement>('[title="参考原文编辑区"]')!
    await act(async () => frame.dispatchEvent(new Event('load')))
    const input = frame.contentDocument!.body
    if (commandChangesDom) {
      Object.defineProperty(frame.contentDocument!, 'execCommand', { configurable: true, value: vi.fn((_command, _ui, html: string) => {
        input.insertAdjacentHTML('beforeend', html)
        return false
      }) })
    }
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { getData: (type: string) => type === 'text/html' ? '<p style="color:red">正文</p>' : '正文' } })
    await act(async () => { input.dispatchEvent(event) })
    await act(async () => button('解析粘贴内容').click())
    expect(paste).toHaveBeenLastCalledWith('<p style="color:red">正文</p>', 'html', '', false)
    await act(async () => {
      input.querySelector('p')!.textContent = '修改的原文'
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => button('解析粘贴内容').click())
    expect(paste).toHaveBeenLastCalledWith('<p style="color:red">修改的原文</p>', 'html', '', false)
  })

  it('offers external image transfer explicitly and requires asset authorization before applying', async () => {
    const pasted: LayoutReferencePreview = {
      reference_id: 'pasted', canonical_url: '', title: 'Pasted', site_name: '粘贴内容', preview_html: '<p>正文</p>',
      summary: { extracted_from: '粘贴的 HTML', block_count: 1, image_slots: 1, image_assets: 0 },
      assets: [], warning: '', requires_asset_reuse_confirmation: false,
    }
    const paste = vi.spyOn(layoutReferencesApi, 'paste').mockResolvedValue(pasted)
    await render(false)
    await act(async () => Array.from(document.querySelectorAll('label.ant-segmented-item'))
      .find(item => item.textContent === 'HTML 源码')!.querySelector<HTMLInputElement>('input')!.click())
    const input = document.querySelector<HTMLTextAreaElement>('[aria-label="参考 HTML 源码"]')!
    const source = '<p>正文<img src="https://example.test/image.png"></p>'
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, source)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const transfer = Array.from(document.querySelectorAll('label.ant-checkbox-wrapper'))
      .find(item => item.textContent === '转存外部图片')!.querySelector<HTMLInputElement>('input')!
    expect(transfer.checked).toBe(false)
    await act(async () => button('解析粘贴内容').click())
    expect(paste).toHaveBeenLastCalledWith(source, 'html', '', false)
    expect(button('确认并开始模仿').disabled).toBe(false)
    await act(async () => transfer.click())
    expect(button('确认并开始模仿').disabled).toBe(true)
    paste.mockResolvedValue({ ...pasted, requires_asset_reuse_confirmation: true,
      assets: [{ asset_id: 'image-1', preview_url: '/api/image-1', content_type: 'image/png',
        role: '背景装饰', width: 100, height: 100, usage_count: 1, default_selected: true }],
    })
    await act(async () => button('解析粘贴内容').click())
    expect(paste).toHaveBeenLastCalledWith(source, 'html', '', true)
    expect(button('确认并开始模仿').disabled).toBe(true)
    const authorization = Array.from(document.querySelectorAll('label.ant-checkbox-wrapper'))
      .find(item => item.textContent?.includes('复用授权'))!.querySelector<HTMLInputElement>('input')!
    await act(async () => authorization.click())
    await act(async () => button('确认并开始模仿').click())
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ reference_id: 'pasted' }), true, ['image-1'], 'structure')
    await act(async () => Array.from(document.querySelectorAll('label.ant-segmented-item'))
      .find(item => item.textContent === '粘贴原文')!.querySelector<HTMLInputElement>('input')!.click())
    const resetTransfer = Array.from(document.querySelectorAll('label.ant-checkbox-wrapper'))
      .find(item => item.textContent === '转存外部图片')!.querySelector<HTMLInputElement>('input')!
    expect(resetTransfer.checked).toBe(false)
  })

})
