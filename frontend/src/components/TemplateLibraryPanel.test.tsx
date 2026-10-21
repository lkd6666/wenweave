// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TemplateLibraryPanel from './TemplateLibraryPanel'
import { templateLibraryApi } from '../api/templateLibrary'
import { gzhThemesApi } from '../api/gzhThemes'
import type { GzhThemeItem, TemplateItem } from '../types'

const template: TemplateItem = {
  id: 1, name: 'Footer', category_id: null, html: '<p>Footer</p>', source_type: 'source',
  image_warnings: [], created_at: '', updated_at: '',
}

describe('resource controls during article editing', () => {
  let root: Root
  let container: HTMLDivElement
  const onToggleAttach = vi.fn()
  const onOpenThemeGallery = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    onToggleAttach.mockClear()
    onOpenThemeGallery.mockClear()
    vi.spyOn(templateLibraryApi, 'listCategories').mockResolvedValue([])
    vi.spyOn(templateLibraryApi, 'listTemplates').mockResolvedValue([template])
    vi.spyOn(gzhThemesApi, 'list').mockResolvedValue([{
      key: 'news', name: 'News', scenarios: [], accent_color: '#1677ff',
    } as unknown as GzhThemeItem])
    vi.spyOn(gzhThemesApi, 'preview').mockResolvedValue({ html: '<p>News</p>' })
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

  async function render(attachedTemplateIds: number[] = [], attachmentDisabled = false, tab: 'templates' | 'themes' = 'templates') {
    await act(async () => root.render(<TemplateLibraryPanel
      modelId={null} models={[]} disabled attachmentDisabled={attachmentDisabled}
      canInsertAtCaret={false} attachedTemplateIds={attachedTemplateIds} themeContext={null}
      onAppend={vi.fn()} onInsertAtCaret={vi.fn()} onToggleAttach={onToggleAttach}
      onClearThemeContext={vi.fn()} onOpenThemeGallery={onOpenThemeGallery}
      collection={null} onCollectionHandled={vi.fn()} activeResourceTab={tab}
      onResourceTabChange={vi.fn()} imagePanel={null}
    />))
  }

  function button(label: string) {
    return container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!
  }

  it('allows attaching and removing a reference while article insertion stays locked', async () => {
    await render()
    expect(button('添加 Footer 到文末').disabled).toBe(true)
    expect(button('插入 Footer 到光标处').disabled).toBe(true)
    expect(button('附加模板 Footer').disabled).toBe(false)
    await act(async () => button('附加模板 Footer').click())
    expect(onToggleAttach).toHaveBeenCalledExactlyOnceWith(template)
    await render([1, 2, 3, 4, 5, 6])
    expect(button('移除模板 Footer').disabled).toBe(false)
    await act(async () => button('移除模板 Footer').click())
    expect(onToggleAttach).toHaveBeenCalledTimes(2)
  })

  it('keeps attachment limits and unavailable conversation controls enforced', async () => {
    await render([2, 3, 4, 5, 6, 7])
    expect(button('附加模板 Footer').disabled).toBe(true)
    await render([], true)
    expect(button('附加模板 Footer').disabled).toBe(true)
  })

  it('allows creating a new resource while existing template assets stay protected', async () => {
    await render()
    expect(button('新建模板').disabled).toBe(false)
    expect(button('编辑模板 Footer').disabled).toBe(true)
    expect(button('删除模板 Footer').disabled).toBe(true)
    await act(async () => button('新建模板').click())
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('新建模板')
  })

  it('allows browsing themes during article editing without a selected model', async () => {
    await render([], false, 'themes')
    const open = container.querySelector<HTMLButtonElement>('.theme-library-open-button')!
    expect(open.disabled).toBe(false)
    await act(async () => open.click())
    expect(onOpenThemeGallery).toHaveBeenCalledExactlyOnceWith()
    const preview = container.querySelector<HTMLButtonElement>('.theme-library-preview-card')!
    expect(preview.disabled).toBe(false)
    await act(async () => preview.click())
    expect(onOpenThemeGallery).toHaveBeenLastCalledWith('news')
  })
})
