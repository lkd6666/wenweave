import { describe, expect, it } from 'vitest'
import { Window } from 'happy-dom'
import { collectSvgImageLayers } from './svgImageLayers'

describe('collectSvgImageLayers', () => {
  it('lists each SVG picture once in document order, including legacy xlink sources', () => {
    const document = new Window().document as unknown as Document
    document.body.innerHTML = '<section><svg><image href="first.png" title="第一张"/><g><image xlink:href="second.png"/></g></svg></section>'
    const section = document.querySelector('section')!
    const svg = document.querySelector('svg')!

    expect(collectSvgImageLayers([section, svg]).map(({ source, label }) => ({ source, label }))).toEqual([
      { source: 'first.png', label: '第一张' },
      { source: 'second.png', label: '' },
    ])
  })

  it('keeps distinct pictures when they share one source', () => {
    const document = new Window().document as unknown as Document
    document.body.innerHTML = '<svg><image href="same.png"/><image href="same.png"/></svg>'

    expect(collectSvgImageLayers([document.querySelector('svg')!])).toHaveLength(2)
  })

  it('uses document order even if the user selects containers in reverse', () => {
    const document = new Window().document as unknown as Document
    document.body.innerHTML = '<section><svg><image href="first.png"/></svg></section><section><svg><image href="second.png"/></svg></section>'
    const sections = Array.from(document.querySelectorAll('section'))

    expect(collectSvgImageLayers(sections.reverse()).map((layer) => layer.source)).toEqual(['first.png', 'second.png'])
  })
})
