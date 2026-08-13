import { DOMParser, XMLSerializer } from '@xmldom/xmldom'
import { describe, expect, it } from 'vitest'
import { applyLibraryImageToDom, resolveImageApplicationTarget, stepEditHistory } from './editorImageApplication'

function article(markup = '<body><p id="first">第一段</p><p id="second">第二段</p></body>') {
  const document = new DOMParser().parseFromString(markup, 'text/xml') as unknown as Document
  const body = document.getElementsByTagName('body')[0] as unknown as HTMLElement
  const serialize = () => new XMLSerializer().serializeToString(body as unknown as Node)
  return { document, body, serialize }
}

describe('editor image application', () => {
  it('does nothing without a valid canvas target', () => {
    const { document, body, serialize } = article()
    const before = serialize()

    expect(resolveImageApplicationTarget(body, null, null, null)).toBeNull()
    expect(applyLibraryImageToDom(document, body, null, '/next.png', '图片')).toBeNull()
    expect(serialize()).toBe(before)
  })

  it('inserts after a caret block', () => {
    const { document, body, serialize } = article()
    const caret = document.getElementById('first') as unknown as HTMLElement
    const target = resolveImageApplicationTarget(body, null, null, caret)

    const result = applyLibraryImageToDom(document, body, target, '/caret.png', '光标配图')

    expect(result?.mode).toBe('insert')
    expect(serialize()).toContain('<p id="first">第一段</p><p><img src="/caret.png" alt="光标配图"')
  })

  it('uses the selected block before a stale caret block', () => {
    const { document, body, serialize } = article()
    const caret = document.getElementById('first') as unknown as HTMLElement
    const block = document.getElementById('second') as unknown as HTMLElement
    const target = resolveImageApplicationTarget(body, null, block, caret)

    applyLibraryImageToDom(document, body, target, '/block.png', '块后配图')

    expect(target?.kind).toBe('block')
    expect(serialize()).toContain('<p id="second">第二段</p><p><img src="/block.png"')
  })

  it('replaces an image while preserving its container, alt and dimensions', () => {
    const { document, body, serialize } = article('<body><figure class="hero"><img src="/old.png" alt="原图" style="width:62%" srcset="old-2x.png 2x" data-crop-source="crop.png"/></figure></body>')
    const image = document.getElementsByTagName('img')[0] as unknown as HTMLImageElement
    const block = document.getElementsByTagName('figure')[0] as unknown as HTMLElement
    const target = resolveImageApplicationTarget(body, image, block, null)

    const result = applyLibraryImageToDom(document, body, target, '/new.png', '不应覆盖')

    expect(result?.mode).toBe('replace')
    expect(target?.kind).toBe('image')
    expect(serialize()).toBe('<body><figure class="hero"><img src="/new.png" alt="原图" style="width:62%"/></figure></body>')
  })

  it('turns a second click into replacement of the newly inserted image', () => {
    const { document, body, serialize } = article()
    const block = document.getElementById('first') as unknown as HTMLElement
    const inserted = applyLibraryImageToDom(
      document,
      body,
      resolveImageApplicationTarget(body, null, block, null),
      '/first.png',
      '第一张',
    )
    const replacementTarget = resolveImageApplicationTarget(body, inserted?.image ?? null, block, null)

    const replaced = applyLibraryImageToDom(document, body, replacementTarget, '/second.png', '第二张')

    expect(replaced?.mode).toBe('replace')
    expect(document.getElementsByTagName('img')).toHaveLength(1)
    expect(serialize()).toContain('src="/second.png" alt="第一张"')
  })

  it('moves image edits through undo and redo history', () => {
    const { document, body, serialize } = article()
    const before = serialize()
    const block = document.getElementById('first') as unknown as HTMLElement
    applyLibraryImageToDom(document, body, resolveImageApplicationTarget(body, null, block, null), '/history.png', '历史')
    const after = serialize()
    const undoStack = [before]
    const redoStack: string[] = []

    expect(stepEditHistory('undo', after, undoStack, redoStack)).toBe(before)
    expect(stepEditHistory('redo', before, undoStack, redoStack)).toBe(after)
    expect(undoStack).toEqual([before])
    expect(redoStack).toEqual([])
  })
})
