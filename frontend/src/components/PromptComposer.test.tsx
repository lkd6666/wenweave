// @vitest-environment happy-dom
import { act, createRef } from 'react'
import type { ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PromptComposer from './PromptComposer'
import type { PromptComposerHandle } from './PromptComposer'
import type { ChatImageAttachment, SelectedElementContext, TemplateItem } from '../types'

describe('composer clipboard images', () => {
  let container: HTMLDivElement
  let root: Root
  const onChange = vi.fn()
  const onPasteImages = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    onChange.mockClear()
    onPasteImages.mockClear()
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  async function paste(text: string, files: File[]) {
    await act(async () => root.render(<PromptComposer
      value="" references={[]} templates={[]} acceptImages
      onChange={onChange} onPasteImages={onPasteImages}
      onSubmit={vi.fn()} onRemoveReference={vi.fn()} onDuplicateReference={vi.fn()}
      onMoveReference={vi.fn()} onRemoveTemplate={vi.fn()}
    />))
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: {
      items: files.map((file) => ({ kind: 'file', type: file.type, getAsFile: () => file })),
      getData: (type: string) => type === 'text/plain' ? text : '<img src="untrusted">',
    } })
    await act(async () => { container.querySelector('[role="textbox"]')!.dispatchEvent(event) })
    return event
  }

  it('passes pasted pixels to upload while keeping the accompanying instruction', async () => {
    const file = new File(['pixels'], 'pasted.png', { type: 'image/png' })
    const event = await paste('用这张图替换第二张图片', [file])
    expect(event.defaultPrevented).toBe(true)
    expect(onPasteImages).toHaveBeenCalledWith([file])
    expect(onChange).toHaveBeenCalledWith('用这张图替换第二张图片')
    expect(container.querySelector('img')).toBeNull()
  })

  it('accepts multiple clipboard images without inserting uncontrolled markup', async () => {
    const files = ['first.png', 'second.png'].map((name) => new File(['pixels'], name, { type: 'image/png' }))
    await paste('', files)
    expect(onPasteImages).toHaveBeenCalledWith(files)
    expect(container.querySelector('img')).toBeNull()
  })
})

const photo = (id: string): ChatImageAttachment => ({
  id, filename: `${id}.png`, content_type: 'image/png', size: 24, preview_url: `/photos/${id}.png`,
})
const element: SelectedElementContext = { selector: 'article > img', tag_name: 'img', html: '<img src="old.png">', text: '' }
const template = { id: 8, name: '图文组件' } as TemplateItem

describe('inline image references', () => {
  let container: HTMLDivElement
  let root: Root
  let composer: ReturnType<typeof createRef<PromptComposerHandle>>
  let props: ComponentProps<typeof PromptComposer>

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    composer = createRef<PromptComposerHandle>()
    props = {
      value: '', references: [], templates: [], images: [], onChange: vi.fn(), onSubmit: vi.fn(),
      onRemoveReference: vi.fn(), onDuplicateReference: vi.fn(), onMoveReference: vi.fn(),
      onRemoveTemplate: vi.fn(), onRemoveImage: vi.fn(), onMoveImage: vi.fn(),
    }
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    window.getSelection()?.removeAllRanges()
    vi.unstubAllGlobals()
  })

  async function render(next: Partial<typeof props> = {}) {
    props = { ...props, ...next }
    await act(async () => root.render(<PromptComposer ref={composer} {...props} />))
  }

  it('restores a draft with images, text, elements and templates in the same flow', async () => {
    await render({
      value: '用@图片1替换@元素1，然后按@组件1排版，再插入@图片2',
      images: [photo('first'), photo('second')], references: [element], templates: [template],
    })
    expect(composer.current!.getPayload()).toEqual({
      message: '用@图片1替换@元素1，然后按@组件1排版，再插入@图片2',
      imageIds: ['first', 'second'], references: [element], templateIds: [8],
    })
    const tokens = container.querySelectorAll('[data-image-token], [data-reference-token], [data-template-token]')
    expect(Array.from(tokens).map((token) => (token as HTMLElement).className)).toEqual([
      'prompt-image-token', 'prompt-reference-token', 'prompt-template-token', 'prompt-image-token',
    ])
    const message = composer.current!.getPayload().message
    await act(async () => root.render(<PromptComposer key="restored" ref={composer} {...props} value={message} />))
    expect(composer.current!.getPayload().message).toBe(message)
  })

  it('serializes all one hundred image references without losing their mixed order', async () => {
    const images = Array.from({ length: 100 }, (_, i) => photo(`photo-${i}`))
    const value = images.map((_, i) => `第${i + 1}张@图片${i + 1}`).join('，') + '替换@元素1，按@组件1排版'
    await render({ value, images, references: [element], templates: [template] })
    expect(container.querySelectorAll('[data-image-token]')).toHaveLength(100)
    expect(composer.current!.getPayload()).toEqual({ message: value, imageIds: images.map((image) => image.id), references: [element], templateIds: [8] })
  })

  it('inserts an asynchronous batch at the saved caret after focus moves to the gallery', async () => {
    await render({ value: '前后' })
    const editor = container.querySelector<HTMLElement>('[role="textbox"]')!
    editor.focus()
    const range = document.createRange()
    range.setStart(editor.firstChild!, 1)
    range.collapse(true)
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    editor.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    const galleryInput = document.createElement('input')
    container.append(galleryInput)
    galleryInput.focus()
    window.getSelection()!.removeAllRanges()
    await render({ images: [photo('first'), photo('second')] })
    expect(composer.current!.getPayload().message).toBe('前@图片1@图片2后')
    expect(container.querySelectorAll('[data-image-group]')).toHaveLength(1)
    expect(composer.current!.getPayload().imageIds).toEqual(['first', 'second'])
    expect(document.activeElement).toBe(galleryInput)
    await render({ value: composer.current!.getPayload().message, images: [photo('first'), photo('second')] })
    expect(composer.current!.getPayload().message).toBe('前@图片1@图片2后')
  })

  it('collapses one hundred adjacent images without changing the outgoing references or draft', async () => {
    const images = Array.from({ length: 100 }, (_, i) => photo(`photo-${i}`))
    const value = '请使用' + images.map((_, i) => `@图片${i + 1}`).join('') + '替换@元素1并按@组件1排版'
    await render({ value, images, references: [element], templates: [template] })
    expect(container.querySelectorAll('[data-image-group]')).toHaveLength(1)
    expect(container.querySelector('[data-image-group-label]')?.textContent).toBe('@图片1-100 · 100 张')
    expect(composer.current!.getPayload()).toEqual({ message: value, imageIds: images.map((image) => image.id), references: [element], templateIds: [8] })
    await act(async () => root.render(<PromptComposer key="restored" ref={composer} {...props} />))
    expect(container.querySelectorAll('[data-image-group]')).toHaveLength(1)
    expect(composer.current!.getPayload().message).toBe(value)
  })

  it('keeps image groups on each side of text and component references', async () => {
    const images = ['one', 'two', 'three', 'four', 'five'].map(photo)
    const value = '@图片1@图片2用作正文@元素1，@图片3@图片4按@组件1排版，@图片5用作封面'
    await render({ value, images, references: [element], templates: [template] })
    expect(container.querySelectorAll('[data-image-group]')).toHaveLength(2)
    expect(composer.current!.getPayload().message).toBe(value)
    expect(composer.current!.getPayload().imageIds).toEqual(images.map((image) => image.id))
  })

  it('expands a group and removes one image while preserving its neighbors', async () => {
    const images = ['one', 'two', 'three'].map(photo)
    await render({ value: '前@图片1@图片2@图片3后', images })
    await act(async () => container.querySelector<HTMLButtonElement>('[data-image-group-action="open"]')!.click())
    expect(document.querySelector('.ant-modal-title')?.textContent).toBe('引用图片（3 张）')
    expect(document.querySelector('.prompt-image-group-list')?.textContent).toContain('two.png')
    const remove = document.querySelector<HTMLButtonElement>('.prompt-image-group-list [aria-label="移除图片 two.png"]')!
    await act(async () => remove.click())
    expect(props.onRemoveImage).toHaveBeenCalledExactlyOnceWith(images[1])
    expect(composer.current!.getPayload()).toMatchObject({ message: '前@图片1@图片2后', imageIds: ['one', 'three'] })
    expect(container.querySelector('[data-image-group-label]')?.textContent).toBe('@图片1-2 · 2 张')
  })

  it('removes all images in the chosen group without removing other mixed content', async () => {
    const images = ['one', 'two', 'three'].map(photo)
    await render({ value: '@图片1@图片2替换@元素1，保留@图片3', images, references: [element] })
    await act(async () => container.querySelector<HTMLButtonElement>('[data-image-group-action="remove"]')!.click())
    expect(props.onRemoveImage).toHaveBeenCalledTimes(2)
    expect(composer.current!.getPayload()).toMatchObject({ message: '替换@元素1，保留@图片1', imageIds: ['three'], references: [element] })
  })

  it('moves a collapsed group as one token and preserves image order', async () => {
    await render({ value: '@图片1@图片2正文@图片3', images: ['one', 'two', 'three'].map(photo) })
    const group = container.querySelector<HTMLElement>('[data-image-group]')!
    const last = container.querySelector<HTMLElement>('[data-image-token="three"]')!
    const start = new Event('dragstart', { bubbles: true })
    Object.defineProperty(start, 'dataTransfer', { value: { setData: vi.fn() } })
    const drop = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(drop, 'clientX', { value: 1 })
    await act(async () => { group.dispatchEvent(start); last.dispatchEvent(drop) })
    expect(composer.current!.getPayload().imageIds).toEqual(['three', 'one', 'two'])
    expect(props.onMoveImage).toHaveBeenCalledWith(2, 0)
    expect(container.querySelector('[data-image-group-label]')?.textContent).toBe('@图片1-3 · 3 张')
  })

  it('merges a later batch into the existing group at the saved caret', async () => {
    const images = ['one', 'two', 'three', 'four'].map(photo)
    await render({ value: '前后' })
    const editor = container.querySelector<HTMLElement>('[role="textbox"]')!
    editor.focus()
    const range = document.createRange()
    range.setStart(editor.firstChild!, 1)
    range.collapse(true)
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    editor.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    await render({ images: images.slice(0, 2) })
    await render({ value: composer.current!.getPayload().message, images })
    expect(container.querySelectorAll('[data-image-group]')).toHaveLength(1)
    expect(composer.current!.getPayload()).toMatchObject({ message: '前@图片1@图片2@图片3@图片4后', imageIds: images.map((image) => image.id) })
    expect(composer.current!.getPayload().message).not.toContain('\u200b')
  })

  it('returns to a single image token when only one image remains', async () => {
    const images = ['one', 'two'].map(photo)
    await render({ value: '前@图片1@图片2后', images })
    await act(async () => container.querySelector<HTMLButtonElement>('[data-image-group-action="open"]')!.click())
    await act(async () => document.querySelector<HTMLButtonElement>('.prompt-image-group-list [aria-label="移除图片 one.png"]')!.click())
    expect(container.querySelectorAll('[data-image-group]')).toHaveLength(0)
    expect(composer.current!.getPayload()).toMatchObject({ message: '前@图片1后', imageIds: ['two'] })
  })

  it('removes each attachment once when a group is deleted with the keyboard', async () => {
    await render({ value: '@图片1@图片2说明', images: ['one', 'two'].map(photo) })
    await act(async () => {
      container.querySelector('[data-image-group]')!.remove()
      container.querySelector('[role="textbox"]')!.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(props.onRemoveImage).toHaveBeenCalledTimes(2)
    expect(composer.current!.getPayload()).toMatchObject({ message: '说明', imageIds: [] })
    await render({ value: '说明' })
    expect(composer.current!.getPayload().imageIds).toEqual([])
  })

  it('updates outgoing image order and numbering after drag and drop', async () => {
    await render({ value: '用@图片1和@图片2', images: [photo('first'), photo('second')] })
    const first = container.querySelector<HTMLElement>('[data-image-token="first"]')!
    const second = container.querySelector<HTMLElement>('[data-image-token="second"]')!
    const start = new Event('dragstart', { bubbles: true })
    Object.defineProperty(start, 'dataTransfer', { value: { setData: vi.fn() } })
    const drop = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(drop, 'clientX', { value: -1 })
    await act(async () => { second.dispatchEvent(start); first.dispatchEvent(drop) })
    expect(props.onMoveImage).toHaveBeenCalledWith(1, 0)
    expect(composer.current!.getPayload().imageIds).toEqual(['second', 'first'])
    expect(second.querySelector('[data-image-label]')!.textContent).toBe('@图片1')
    await render({ value: composer.current!.getPayload().message, images: [photo('second'), photo('first')] })
    expect(composer.current!.getPayload().imageIds).toEqual(['second', 'first'])
  })

  it('removes only the chosen image and reports removal once', async () => {
    const first = photo('first')
    const second = photo('second')
    await render({ value: '保留@图片1，移除@图片2', images: [first, second] })
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-image-token="second"] button')!.click() })
    expect(props.onRemoveImage).toHaveBeenCalledExactlyOnceWith(second)
    const editor = container.querySelector('[role="textbox"]')!
    await act(async () => { editor.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(props.onRemoveImage).toHaveBeenCalledTimes(1)
    await render({ value: composer.current!.getPayload().message, images: [first] })
    expect(composer.current!.getPayload().imageIds).toEqual(['first'])
  })

  it('synchronizes keyboard deletion and renumbers the remaining image', async () => {
    const first = photo('first')
    await render({ value: '@图片1替换原图，@图片2备用', images: [first, photo('second')] })
    await act(async () => {
      container.querySelector('[data-image-token="first"]')!.remove()
      container.querySelector('[role="textbox"]')!.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(props.onRemoveImage).toHaveBeenCalledExactlyOnceWith(first)
    expect(composer.current!.getPayload().imageIds).toEqual(['second'])
    // Browser deletion emits input rather than the token button click.
    expect(composer.current!.getPayload().message).toContain('@图片1')
  })
})
