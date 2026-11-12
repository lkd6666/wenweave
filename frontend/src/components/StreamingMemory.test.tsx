// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TemplateLibraryPanel from './TemplateLibraryPanel'
import ElementRenderPreview from './ElementRenderPreview'
import { AiThinkingReasoning, AiToolCall } from './AiOutput'

vi.mock('../api/templateLibrary', () => ({
  templateLibraryApi: {
    listCategories: async () => [],
    listTemplates: async () => [{ id: 1, name: '模板', html: '<p>模板正文</p>', category_id: null, source_type: 'source' }],
  },
}))
vi.mock('../api/gzhThemes', () => ({
  gzhThemesApi: {
    list: async () => [{ key: 'test', name: '主题', accent_color: '#000', scenarios: [] }],
    preview: async () => ({ html: '<p>主题正文</p>' }),
  },
}))

let container: HTMLDivElement
let root: Root
const noop = () => undefined

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  // happy-dom lacks complete iframe Documents; browser QA covers load/height.
  vi.spyOn(HTMLIFrameElement.prototype, 'contentDocument', 'get').mockReturnValue(null)
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

describe('streaming render resource lifetime', () => {
  it('keeps long reasoning complete with bounded nodes and releases collapsed history', async () => {
    const content = '先核对文章结构。保留原文中的全部信息。\n'.repeat(1000)
    await act(async () => root.render(<AiThinkingReasoning thinking content={content} />))
    const viewport = container.querySelector('.aicss-thinking-reasoning-viewport')!
    expect(viewport.querySelectorAll('*').length).toBeLessThan(10)
    expect(viewport.textContent).toBe(content)
    await act(async () => root.render(<AiThinkingReasoning thinking={false} content={content} />))
    expect(container.textContent).not.toContain('先核对')
    await act(async () => container.querySelector<HTMLButtonElement>('button')?.click())
    expect(container.querySelector('.aicss-thinking-reasoning-viewport')?.textContent).toBe(content)
  })

  it.each(['templates', 'themes'] as const)('does not create new %s documents during unrelated parent updates', async (tab) => {
    const parse = vi.spyOn(DOMParser.prototype, 'parseFromString')
    const render = () => <TemplateLibraryPanel
      modelId={null} models={[]} disabled canInsertAtCaret={false} attachedTemplateIds={[]}
      themeContext={null} onPrepend={noop} onAppend={noop} onInsertAtCaret={noop} onAttachToChat={noop}
      onClearThemeContext={noop} onOpenThemeGallery={noop} collection={null}
      onCollectionHandled={noop} activeResourceTab={tab} onResourceTabChange={noop} imagePanel={null}
    />
    await act(async () => root.render(render()))
    expect(container.querySelectorAll('iframe')).toHaveLength(1)
    const initialParses = parse.mock.calls.length
    expect(initialParses).toBeGreaterThan(0)

    for (let delta = 0; delta < 30; delta += 1) {
      await act(async () => root.render(render()))
    }

    expect(parse).toHaveBeenCalledTimes(initialParses)
    expect(container.querySelector('iframe')?.srcdoc).toContain('正文')
  })

  it('reuses element previews until their HTML changes and preserves link isolation', async () => {
    const parse = vi.spyOn(DOMParser.prototype, 'parseFromString')
    const html = '<a href="https://example.com">原内容</a>'
    await act(async () => root.render(<ElementRenderPreview html={html} />))
    const initialParses = parse.mock.calls.length
    for (let delta = 0; delta < 30; delta += 1) {
      await act(async () => root.render(<ElementRenderPreview html={html} />))
    }
    expect(parse).toHaveBeenCalledTimes(initialParses)
    expect(container.querySelector('iframe')?.srcdoc).toContain('target="_blank"')
    await act(async () => root.render(<ElementRenderPreview html="<p>新内容</p>" />))
    expect(container.querySelector('iframe')?.srcdoc).toContain('新内容')
    expect(parse.mock.calls.length).toBeGreaterThan(initialParses)
  })

  it('mounts tool details only while expanded and releases them on collapse', async () => {
    const mounts = vi.fn()
    function ExpensiveDetails() {
      mounts()
      return <pre>完整工具内容</pre>
    }
    const render = (expanded: boolean) => <AiToolCall title="读取" summary="完成" status="success" icon={null} expanded={expanded} onToggle={noop}><ExpensiveDetails /></AiToolCall>
    await act(async () => root.render(render(false)))
    expect(mounts).not.toHaveBeenCalled()
    expect(container.querySelector('pre')).toBeNull()
    await act(async () => root.render(render(true)))
    expect(container.querySelector('pre')?.textContent).toBe('完整工具内容')
    await act(async () => root.render(render(false)))
    expect(container.querySelector('pre')).toBeNull()
    await act(async () => root.render(render(true)))
    expect(container.querySelector('pre')?.textContent).toBe('完整工具内容')
  })
})
