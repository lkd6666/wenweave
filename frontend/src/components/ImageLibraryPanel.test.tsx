// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ImageLibraryPanel from './ImageLibraryPanel'
import { imageLibraryApi } from '../api/imageLibrary'
import type { ImageLibraryAsset } from '../types'

describe('gallery batch references', () => {
  let container: HTMLDivElement
  let root: Root
  const onReference = vi.fn(async (_ids: string[]) => true)

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    onReference.mockClear()
    vi.spyOn(imageLibraryApi, 'list').mockImplementation(async ({ page = 1 } = {}) => ({
      total: 108, page, page_size: 18, mode: 'personal',
      items: Array.from({ length: 18 }, (_, offset) => {
        const id = (page - 1) * 18 + offset + 1
        return { id: `asset-${id}`, name: `photo-${id}.png`, url: `/photo-${id}.png`, source: 'upload' } as ImageLibraryAsset
      }),
    }))
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

  async function render(disabled = false, uploadDisabled = false) {
    await act(async () => root.render(<ImageLibraryPanel
      documentId={1} sessionId={1} applicationTarget={null} selectedImage={null}
      onApply={vi.fn()} onSetCover={vi.fn()} onReference={onReference}
      disabled={disabled} uploadDisabled={uploadDisabled}
    />))
  }

  async function selectPage() {
    const label = Array.from(container.querySelectorAll('label')).find((item) => item.textContent?.includes('本页全选'))!
    await act(async () => label.querySelector<HTMLInputElement>('input')!.click())
  }

  async function nextPage() {
    await act(async () => container.querySelector<HTMLButtonElement>('.ant-pagination-next button')!.click())
  }

  it('retains selections across pages and references at most one hundred assets in selection order', async () => {
    await render()
    for (let page = 1; page <= 6; page += 1) {
      await selectPage()
      if (page < 6) await nextPage()
    }
    const reference = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('附到对话 (100)'))!
    expect(reference).toBeDefined()
    expect(container.querySelectorAll('.image-library-select input:checked')).toHaveLength(10)
    await act(async () => container.querySelector<HTMLInputElement>('[aria-label="选择图片：photo-101.png"]')!.click())
    expect(container.querySelectorAll('.image-library-select input:checked')).toHaveLength(10)
    await act(async () => reference.click())
    expect(onReference).toHaveBeenCalledExactlyOnceWith(Array.from({ length: 100 }, (_, i) => `asset-${i + 1}`))
    expect(container.querySelectorAll('.image-library-select input:checked')).toHaveLength(0)
  })

  it('deselects only the visible page while preserving earlier selections', async () => {
    await render()
    await selectPage()
    await nextPage()
    await selectPage()
    await selectPage()
    const reference = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('附到对话 (18)'))!
    await act(async () => reference.click())
    expect(onReference).toHaveBeenCalledExactlyOnceWith(Array.from({ length: 18 }, (_, i) => `asset-${i + 1}`))
  })

  it('allows uploads and conversation references while article application stays locked', async () => {
    const upload = vi.spyOn(imageLibraryApi, 'upload').mockResolvedValue([])
    await render(true)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="上传图片"]')!.disabled).toBe(false)
    expect(container.querySelector<HTMLButtonElement>('.image-library-apply')!.disabled).toBe(true)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="设为封面：photo-1.png"]')!.disabled).toBe(true)
    const reference = container.querySelector<HTMLButtonElement>('[aria-label="引用到对话：photo-1.png"]')!
    expect(reference.disabled).toBe(false)
    await act(async () => reference.click())
    expect(onReference).toHaveBeenCalledExactlyOnceWith(['asset-1'])
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    const file = new File(['pixels'], 'new.png', { type: 'image/png' })
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    expect(upload).toHaveBeenCalledOnce()
    expect(upload.mock.calls[0]![1]).toEqual([file])
  })

  it('enforces the independent upload lock for drag and file input paths', async () => {
    const upload = vi.spyOn(imageLibraryApi, 'upload').mockResolvedValue([])
    await render(false, true)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="上传图片"]')!.disabled).toBe(true)
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    const file = new File(['pixels'], 'new.png', { type: 'image/png' })
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    const drop = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(drop, 'dataTransfer', { value: { files: [file] } })
    await act(async () => container.querySelector('.image-library-upload-zone')!.dispatchEvent(drop))
    expect(upload).not.toHaveBeenCalled()
  })

  it.each(['file input', 'drop'] as const)('uploads one hundred files through %s and displays transfer, saving and completion progress', async (method) => {
    let finish!: (assets: ImageLibraryAsset[]) => void
    const upload = vi.spyOn(imageLibraryApi, 'upload').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    await render()
    const files = Array.from({ length: 101 }, (_, i) => new File(['pixels'], `photo-${i}.png`, { type: 'image/png' }))
    if (method === 'file input') {
      const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
      Object.defineProperty(input, 'files', { configurable: true, value: files })
      await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    } else {
      const event = new Event('drop', { bubbles: true, cancelable: true })
      Object.defineProperty(event, 'dataTransfer', { value: { files } })
      await act(async () => container.querySelector('.image-library-upload-zone')!.dispatchEvent(event))
      expect(event.defaultPrevented).toBe(true)
    }
    expect(upload).toHaveBeenCalledTimes(1)
    expect(upload.mock.calls[0]![1]).toEqual(files.slice(0, 100))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('正在上传 0/100 张')
    expect(container.querySelector('.image-library-panel')?.firstElementChild).toBe(container.querySelector('.image-library-upload-progress'))
    const onProgress = upload.mock.calls[0]![2]!.onProgress!
    await act(async () => onProgress({ loaded: 50, total: 100 }))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('50%')
    await act(async () => onProgress({ loaded: 100, total: 100 }))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('正在保存 0/100 张')
    expect(container.querySelector('[role="status"]')?.textContent).not.toContain('100%')
    await act(async () => finish([]))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('上传完成 100/100 张')
    expect(container.querySelector('[role="status"]')?.textContent).toContain('100%')
  })

  it('keeps failure progress visible and allows another upload', async () => {
    const upload = vi.spyOn(imageLibraryApi, 'upload').mockRejectedValueOnce(new Error('offline')).mockResolvedValue([])
    await render()
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(input, 'files', { configurable: true, value: [new File(['pixels'], 'photo.png', { type: 'image/png' })] })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('上传结束 0/1 张，1 张失败')
    expect(container.querySelector('[role="status"]')?.textContent).not.toContain('100%')
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    expect(upload).toHaveBeenCalledTimes(2)
    expect(container.querySelector('[role="status"]')?.textContent).toContain('上传完成 1/1 张')
  })
})
