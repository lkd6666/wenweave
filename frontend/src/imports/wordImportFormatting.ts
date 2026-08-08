import JSZip from 'jszip'
import { DOMParser } from '@xmldom/xmldom'

type CssProperties = Record<string, string>

interface StyleDefinition {
  basedOn: string | null
  paragraph: CssProperties
  run: CssProperties
}

interface WordRunFormatting {
  css: CssProperties
  text: string
}

interface WordParagraphFormatting {
  css: CssProperties
  runs: WordRunFormatting[]
}

export interface WordImportFormatting {
  paragraphs: WordParagraphFormatting[]
}

const WORD_DOCUMENT_PATH = 'word/document.xml'
const WORD_STYLES_PATH = 'word/styles.xml'

function localName(node: Node) {
  return (node as Element).localName || node.nodeName.split(':').at(-1) || ''
}

function childElements(node: Node) {
  return Array.from(node.childNodes).filter((child): child is Element => child.nodeType === child.ELEMENT_NODE)
}

function descendantElements(node: Node, name: string): Element[] {
  const elements: Element[] = []
  const visit = (current: Node) => {
    for (const child of childElements(current)) {
      if (localName(child) === name) elements.push(child)
      visit(child)
    }
  }
  visit(node)
  return elements
}

function firstChildElement(node: Node | null | undefined, name: string): Element | null {
  if (!node) return null
  return childElements(node).find((child) => localName(child) === name) ?? null
}

function attribute(element: Element | null | undefined, name: string): string | null {
  if (!element) return null
  return element.getAttribute(name) || element.getAttribute(`w:${name}`) || null
}

function mergeCss(...styles: Array<CssProperties | null | undefined>): CssProperties {
  return Object.assign({}, ...styles.filter((style): style is CssProperties => Boolean(style)))
}

function isWordBooleanEnabled(element: Element | null): boolean | null {
  if (!element) return null
  const value = attribute(element, 'val')
  return value !== 'false' && value !== '0' && value !== 'none'
}

function wordColor(value: string | null): string | null {
  if (!value || value.toLowerCase() === 'auto') return null
  const normalized = value.replace(/^#/, '')
  return /^[0-9a-f]{6}$/i.test(normalized) ? `#${normalized}` : null
}

function twipsToPoints(value: string | null): string | null {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric !== 0 ? `${Number((numeric / 20).toFixed(2))}pt` : null
}

function fontFamily(value: string | null): string | null {
  if (!value) return null
  const safe = value.replace(/["'{};]/g, '').trim()
  return safe ? `'${safe}'` : null
}

function runCss(runProperties: Element | null): CssProperties {
  if (!runProperties) return {}
  const css: CssProperties = {}
  const color = wordColor(attribute(firstChildElement(runProperties, 'color'), 'val'))
  const highlight = wordColor(attribute(firstChildElement(runProperties, 'highlight'), 'val'))
  const fonts = firstChildElement(runProperties, 'rFonts')
  const size = Number(attribute(firstChildElement(runProperties, 'sz'), 'val'))
  const font = fontFamily(attribute(fonts, 'eastAsia') ?? attribute(fonts, 'ascii') ?? attribute(fonts, 'hAnsi'))
  if (color) css.color = color
  if (highlight) css['background-color'] = highlight
  if (font) css['font-family'] = font
  if (Number.isFinite(size) && size > 0) css['font-size'] = `${Number((size / 2).toFixed(2))}pt`

  const bold = isWordBooleanEnabled(firstChildElement(runProperties, 'b'))
  const italic = isWordBooleanEnabled(firstChildElement(runProperties, 'i'))
  const underline = isWordBooleanEnabled(firstChildElement(runProperties, 'u'))
  const strike = isWordBooleanEnabled(firstChildElement(runProperties, 'strike'))
  if (bold !== null) css['font-weight'] = bold ? '700' : '400'
  if (italic !== null) css['font-style'] = italic ? 'italic' : 'normal'
  if (underline !== null) css['text-decoration'] = underline ? 'underline' : 'none'
  if (strike === true) css['text-decoration'] = css['text-decoration'] === 'underline' ? 'underline line-through' : 'line-through'
  return css
}

function paragraphCss(paragraphProperties: Element | null): CssProperties {
  if (!paragraphProperties) return {}
  const css: CssProperties = {}
  const alignment = attribute(firstChildElement(paragraphProperties, 'jc'), 'val')
  const indent = firstChildElement(paragraphProperties, 'ind')
  const spacing = firstChildElement(paragraphProperties, 'spacing')
  const shading = wordColor(attribute(firstChildElement(paragraphProperties, 'shd'), 'fill'))
  const alignments: Record<string, string> = {
    left: 'left',
    right: 'right',
    center: 'center',
    both: 'justify',
    distribute: 'justify',
    start: 'start',
    end: 'end',
  }
  if (alignment && alignments[alignment]) css['text-align'] = alignments[alignment]
  if (shading) css['background-color'] = shading

  const marginLeft = twipsToPoints(attribute(indent, 'start') ?? attribute(indent, 'left'))
  const marginRight = twipsToPoints(attribute(indent, 'end') ?? attribute(indent, 'right'))
  const firstLine = twipsToPoints(attribute(indent, 'firstLine'))
  const hanging = twipsToPoints(attribute(indent, 'hanging'))
  if (marginLeft) css['margin-left'] = marginLeft
  if (marginRight) css['margin-right'] = marginRight
  if (firstLine) css['text-indent'] = firstLine
  if (hanging) css['text-indent'] = `-${hanging}`

  const marginTop = twipsToPoints(attribute(spacing, 'before'))
  const marginBottom = twipsToPoints(attribute(spacing, 'after'))
  const line = Number(attribute(spacing, 'line'))
  const lineRule = attribute(spacing, 'lineRule')
  if (marginTop) css['margin-top'] = marginTop
  if (marginBottom) css['margin-bottom'] = marginBottom
  if (Number.isFinite(line) && line > 0) {
    css['line-height'] = lineRule === 'exact' || lineRule === 'atLeast'
      ? `${Number((line / 20).toFixed(2))}pt`
      : String(Number((line / 240).toFixed(3)))
  }
  return css
}

function collectText(node: Node): string {
  let value = ''
  const visit = (current: Node) => {
    for (const child of childElements(current)) {
      const name = localName(child)
      if (name === 't' || name === 'delText') value += child.textContent ?? ''
      else if (name === 'tab') value += '\t'
      else if (name === 'br' || name === 'cr') value += '\n'
      else if (name !== 'drawing') visit(child)
    }
  }
  visit(node)
  return value
}

function styleId(properties: Element | null, kind: 'pStyle' | 'rStyle'): string | null {
  return attribute(firstChildElement(properties, kind), 'val')
}

function readStyleDefinitions(stylesDocument: XMLDocument | null): {
  defaults: StyleDefinition
  styles: Map<string, StyleDefinition>
} {
  const defaults: StyleDefinition = { basedOn: null, paragraph: {}, run: {} }
  const styles = new Map<string, StyleDefinition>()
  if (!stylesDocument) return { defaults, styles }

  const root = stylesDocument.documentElement
  const documentDefaults = firstChildElement(root, 'docDefaults')
  defaults.paragraph = paragraphCss(firstChildElement(firstChildElement(documentDefaults, 'pPrDefault'), 'pPr'))
  defaults.run = runCss(firstChildElement(firstChildElement(documentDefaults, 'rPrDefault'), 'rPr'))
  for (const element of childElements(root).filter((child) => localName(child) === 'style')) {
    const id = attribute(element, 'styleId')
    if (!id) continue
    styles.set(id, {
      basedOn: attribute(firstChildElement(element, 'basedOn'), 'val'),
      paragraph: paragraphCss(firstChildElement(element, 'pPr')),
      run: runCss(firstChildElement(element, 'rPr')),
    })
  }
  return { defaults, styles }
}

function resolveStyle(
  id: string | null,
  styles: Map<string, StyleDefinition>,
  defaults: StyleDefinition,
  seen = new Set<string>(),
): StyleDefinition {
  if (!id || seen.has(id)) return defaults
  const style = styles.get(id)
  if (!style) return defaults
  seen.add(id)
  const parent = resolveStyle(style.basedOn, styles, defaults, seen)
  return {
    basedOn: null,
    paragraph: mergeCss(parent.paragraph, style.paragraph),
    run: mergeCss(parent.run, style.run),
  }
}

function readParagraphFormatting(document: XMLDocument, styles: Map<string, StyleDefinition>, defaults: StyleDefinition): WordParagraphFormatting[] {
  const paragraphs: WordParagraphFormatting[] = []
  for (const paragraph of descendantElements(document, 'p')) {
    const directParagraphProperties = firstChildElement(paragraph, 'pPr')
    const resolvedParagraphStyle = resolveStyle(styleId(directParagraphProperties, 'pStyle'), styles, defaults)
    const paragraphStyle = mergeCss(resolvedParagraphStyle.paragraph, paragraphCss(directParagraphProperties), resolvedParagraphStyle.run)
    const runs: WordRunFormatting[] = []
    for (const run of descendantElements(paragraph, 'r')) {
      const directRunProperties = firstChildElement(run, 'rPr')
      const characterStyleId = styleId(directRunProperties, 'rStyle')
      const characterStyle = characterStyleId
        ? resolveStyle(characterStyleId, styles, defaults)
        : { basedOn: null, paragraph: {}, run: {} }
      runs.push({
        text: collectText(run),
        css: mergeCss(resolvedParagraphStyle.run, characterStyle.run, runCss(directRunProperties)),
      })
    }
    paragraphs.push({ css: paragraphStyle, runs })
  }
  return paragraphs
}

export async function readWordImportFormatting(buffer: ArrayBuffer): Promise<WordImportFormatting> {
  const zip = await JSZip.loadAsync(buffer)
  const documentFile = zip.file(WORD_DOCUMENT_PATH)
  if (!documentFile) return { paragraphs: [] }
  const [documentXml, stylesXml] = await Promise.all([
    documentFile.async('text'),
    zip.file(WORD_STYLES_PATH)?.async('text') ?? Promise.resolve(null),
  ])
  const parser = new DOMParser()
  const document = parser.parseFromString(documentXml, 'application/xml')
  if (document.getElementsByTagName('parsererror').length > 0) throw new Error('Word 文档 XML 无法解析')
  const stylesDocument = stylesXml ? parser.parseFromString(stylesXml, 'application/xml') : null
  const styleDefinitions = readStyleDefinitions(stylesDocument)
  return { paragraphs: readParagraphFormatting(document, styleDefinitions.styles, styleDefinitions.defaults) }
}

function cssText(css: CssProperties): string {
  return Object.entries(css).map(([property, value]) => `${property}:${value}`).join(';')
}

function addCssToOpeningTag(openingTag: string, css: CssProperties): string {
  if (Object.keys(css).length === 0) return openingTag
  const styleMatch = openingTag.match(/\sstyle=(['"])(.*?)\1/i)
  const additions = Object.entries(css).filter(([property]) => {
    const existing = styleMatch?.[2] ?? ''
    return !new RegExp(`(?:^|;)\\s*${property}\\s*:`, 'i').test(existing)
  })
  if (additions.length === 0) return openingTag
  const nextStyle = [styleMatch?.[2]?.trim(), cssText(Object.fromEntries(additions))].filter(Boolean).join(';')
  if (styleMatch?.index !== undefined) {
    return `${openingTag.slice(0, styleMatch.index)} style="${nextStyle}"${openingTag.slice(styleMatch.index + styleMatch[0].length)}`
  }
  return `${openingTag.slice(0, -1)} style="${nextStyle}">`
}

function decodeEntity(value: string): string {
  const named: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&nbsp;': '\u00a0' }
  if (named[value]) return named[value]
  const decimal = value.match(/^&#(\d+);$/)
  const hexadecimal = value.match(/^&#x([0-9a-f]+);$/i)
  const codePoint = decimal ? Number(decimal[1]) : hexadecimal ? Number.parseInt(hexadecimal[1], 16) : null
  return codePoint === null || !Number.isFinite(codePoint) ? value : String.fromCodePoint(codePoint)
}

function htmlVisibleText(html: string): string {
  return html.replace(/<[^>]*>/g, '').replace(/&(?:#x[0-9a-f]+|#\d+|[a-z]+);/gi, decodeEntity)
}

function rawIndexForTextOffset(html: string, targetOffset: number, boundary: 'start' | 'end'): number | null {
  let rawIndex = 0
  let textOffset = 0
  while (rawIndex < html.length) {
    if (html[rawIndex] === '<') {
      const close = html.indexOf('>', rawIndex)
      if (close < 0) return null
      rawIndex = close + 1
      continue
    }
    if (textOffset === targetOffset) {
      if (boundary === 'end') return rawIndex
      while (html[rawIndex] === '<') {
        const close = html.indexOf('>', rawIndex)
        if (close < 0) return null
        rawIndex = close + 1
      }
      return rawIndex
    }
    if (html[rawIndex] === '&') {
      const entity = html.slice(rawIndex).match(/^&(?:#x[0-9a-f]+|#\d+|[a-z]+);/i)?.[0]
      if (entity) {
        rawIndex += entity.length
        textOffset += decodeEntity(entity).length
        if (textOffset === targetOffset && boundary === 'end') return rawIndex
        continue
      }
    }
    rawIndex += 1
    textOffset += 1
    if (textOffset === targetOffset && boundary === 'end') return rawIndex
  }
  return textOffset === targetOffset ? rawIndex : null
}

function applyRunFormatting(html: string, runs: WordRunFormatting[]): string {
  const textRuns = runs.filter((run) => run.text && Object.keys(run.css).length > 0)
  const expectedText = runs.map((run) => run.text).join('')
  if (!textRuns.length || !expectedText || expectedText !== htmlVisibleText(html)) return html

  const insertions = new Map<number, { starts: string[]; ends: string[] }>()
  const insertAt = (index: number) => {
    const existing = insertions.get(index) ?? { starts: [], ends: [] }
    insertions.set(index, existing)
    return existing
  }
  let offset = 0
  for (const run of runs) {
    const start = offset
    offset += run.text.length
    if (!run.text || Object.keys(run.css).length === 0) continue
    const startIndex = rawIndexForTextOffset(html, start, 'start')
    const endIndex = rawIndexForTextOffset(html, offset, 'end')
    if (startIndex === null || endIndex === null) return html
    insertAt(startIndex).starts.push(`<span style="${cssText(run.css)}">`)
    insertAt(endIndex).ends.unshift('</span>')
  }
  for (const [index, markers] of [...insertions.entries()].sort(([left], [right]) => right - left)) {
    html = `${html.slice(0, index)}${markers.ends.join('')}${markers.starts.join('')}${html.slice(index)}`
  }
  return html
}

/** Add safe inline presentation retained from Word while leaving existing HTML styles untouched. */
export function applyWordImportFormatting(html: string, formatting: WordImportFormatting): string {
  let paragraphIndex = 0
  return html.replace(/<(p|h[1-6]|li)\b[^>]*>[\s\S]*?<\/\1>/gi, (block) => {
    const paragraph = formatting.paragraphs[paragraphIndex]
    paragraphIndex += 1
    if (!paragraph) return block
    const openingEnd = block.indexOf('>') + 1
    const closingStart = block.lastIndexOf('</')
    if (openingEnd <= 0 || closingStart < openingEnd) return block
    const openingTag = addCssToOpeningTag(block.slice(0, openingEnd), paragraph.css)
    const content = applyRunFormatting(block.slice(openingEnd, closingStart), paragraph.runs)
    return `${openingTag}${content}${block.slice(closingStart)}`
  })
}
