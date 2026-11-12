import { describe, expect, it } from 'vitest'
import { Window } from 'happy-dom'
import { normalizeSvgTextBreaks } from './svgTextEditing'

const SVG_NAMESPACE = 'http://www.w3.org/2000/svg'

function editableSvgText(tag = 'text') {
  const document = new Window().document as unknown as Document
  document.body.innerHTML = '<p>正文<br>换行</p><svg viewBox="0 0 130 45"><text x="65" y="21">SPECIAL POST</text></svg>'
  const text = document.createElementNS(SVG_NAMESPACE, tag)
  text.setAttribute('fill', '#846d51')
  document.querySelector('svg')!.append(text)
  // Parsing a string would already repair this invalid tree. Reproduce the
  // mixed namespaces created by the browser's native contenteditable input.
  text.append(document.createElement('br'))
  return { document, text }
}

describe('normalizeSvgTextBreaks', () => {
  it.each(['text', 'tspan', 'textPath'])('keeps cleared SVG %s empty without serializing an HTML br', (tag) => {
    const { document, text } = editableSvgText(tag)
    const clone = document.body.cloneNode(true) as HTMLElement

    normalizeSvgTextBreaks(clone)

    expect(clone.querySelector('svg br')).toBeNull()
    expect(clone.querySelector(tag)?.textContent).toBe(tag === 'text' ? 'SPECIAL POST' : '\n')
    expect(clone.querySelector('[fill]')?.textContent).toBe('\n')
    expect(clone.querySelector('[fill]')?.getAttribute('fill')).toBe('#846d51')
    expect(clone.querySelector('p')?.innerHTML).toBe('正文<br>换行')
    expect(text.querySelector('br')).not.toBeNull()
  })

  it('preserves word separation between edited SVG text runs', () => {
    const { document, text } = editableSvgText()
    text.prepend('first')
    text.append('second')

    normalizeSvgTextBreaks(document.body)

    expect(text.textContent).toBe('first\nsecond')
  })

  it('preserves HTML line breaks in SVG foreignObject, desc and title', () => {
    const { document } = editableSvgText()
    const svg = document.querySelector('svg')!
    for (const tag of ['foreignObject', 'desc', 'title']) {
      const container = document.createElementNS(SVG_NAMESPACE, tag)
      const htmlText = document.createElement('text')
      htmlText.append(document.createElement('br'))
      container.append(htmlText)
      svg.append(container)
    }

    normalizeSvgTextBreaks(document.body)

    expect(svg.querySelectorAll('br')).toHaveLength(3)
  })

  it('normalizes nested SVG text inside foreignObject and accepts a selected text root', () => {
    const { document, text } = editableSvgText()
    const foreign = document.createElementNS(SVG_NAMESPACE, 'foreignObject')
    const nested = document.createElementNS(SVG_NAMESPACE, 'svg')
    document.querySelector('svg')!.append(foreign)
    foreign.append(nested)
    nested.append(text)

    normalizeSvgTextBreaks(text)

    expect(text.querySelector('br')).toBeNull()
    expect(text.textContent).toBe('\n')
  })
})
