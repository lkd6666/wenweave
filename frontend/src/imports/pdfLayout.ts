export interface PdfTextItemLike {
  str: string
  transform: number[]
  width?: number
  height?: number
  hasEOL?: boolean
  fontName?: string
  dir?: string
}

export interface PdfTextStyleLike {
  fontFamily?: string
}

export interface PdfPageComplexity {
  textItemCount: number
  imageCount: number
  pathCount: number
  rotation?: number
}

export interface PdfLayoutBlock {
  kind: 'text' | 'image'
  x: number
  top: number
  width: number
  height: number
  bottom: number
  sourceOrder: number
  fontSize?: number
  html?: string
  clientId?: string
}

interface PdfTextRecord {
  item: PdfTextItemLike
  order: number
  x: number
  top: number
  bottom: number
  width: number
  height: number
  fontSize: number
  baseline: number
}

interface PdfColumn {
  center: number
}

const round = (value: number, digits = 2) => {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

export const escapePdfHtml = (value: string) => value
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const transformPoint = (transform: number[], x: number, y: number) => ({
  x: transform[0] * x + transform[2] * y + transform[4],
  y: transform[1] * x + transform[3] * y + transform[5],
})

function rectBounds(transform: number[], width: number, height: number, pageHeight: number, localX = 0, localY = 0) {
  const corners = [
    transformPoint(transform, localX, localY),
    transformPoint(transform, localX + width, localY),
    transformPoint(transform, localX + width, localY + height),
    transformPoint(transform, localX, localY + height),
  ]
  const minX = Math.min(...corners.map((point) => point.x))
  const maxX = Math.max(...corners.map((point) => point.x))
  const minY = Math.min(...corners.map((point) => point.y))
  const maxY = Math.max(...corners.map((point) => point.y))
  return {
    x: minX,
    top: pageHeight - maxY,
    width: Math.max(0, maxX - minX),
    height: Math.max(0, maxY - minY),
    bottom: pageHeight - minY,
  }
}

function textRecord(item: PdfTextItemLike, order: number, pageHeight: number): PdfTextRecord {
  const transform = item.transform
  const scaleX = Math.max(0.1, Math.hypot(transform[0], transform[1]))
  const scaleY = Math.max(0.1, Math.hypot(transform[2], transform[3]))
  const width = Math.max(0.1, Math.abs(Number(item.width) || scaleX))
  const height = Math.max(0.1, Math.abs(Number(item.height) || scaleY))
  const bounds = rectBounds(transform, width / scaleX, height / scaleY, pageHeight, 0, -(height / scaleY))
  return {
    item,
    order,
    ...bounds,
    fontSize: Math.max(0.1, Math.abs(Number(item.height) || Math.hypot(transform[0], transform[1]))),
    baseline: transform[5],
  }
}

function hasCjk(value: string) {
  return /[\u3400-\u9fff\uf900-\ufaff]/u.test(value)
}

function textSeparator(left: PdfTextRecord, right: PdfTextRecord) {
  const leftText = left.item.str
  const rightText = right.item.str
  if (!leftText || !rightText || /\s$/u.test(leftText) || /^\s/u.test(rightText)) return ''
  if (hasCjk(leftText) || hasCjk(rightText)) return ''
  if (/^[,.;:!?%)]/u.test(rightText) || /^[\u3001\u3002\uff0c\uff01\uff1f\uff1a\uff1b\uff09]/u.test(rightText)) return ''
  if (/[([{\u3008\u300a\u300c\u300e]$/u.test(leftText)) return ''
  const gap = right.x - (left.x + left.width)
  return gap > Math.max(0.75, Math.min(left.height, right.height) * 0.08) ? ' ' : ''
}

function safeFontFamily(value: string | undefined) {
  if (!value) return ''
  const cleaned = value.replace(/[^a-zA-Z0-9 _-]/g, '').trim()
  return cleaned ? `font-family:${cleaned};` : ''
}

/**
 * Rebuild text lines from PDF.js fragments without throwing away content-stream order.
 * PDF.js marks the final fragment of most visual lines with hasEOL; using that signal
 * avoids interleaving the two columns of a document merely because their baselines match.
 */
export function buildPdfTextBlocks(
  items: readonly PdfTextItemLike[],
  styles: Record<string, PdfTextStyleLike> | undefined,
  pageHeight: number,
): PdfLayoutBlock[] {
  const records = items
    .map((item, order) => ({ item, order }))
    .filter(({ item }) => typeof item.str === 'string' && item.str.trim() && Array.isArray(item.transform) && item.transform.length >= 6)
    .map(({ item, order }) => textRecord(item, order, pageHeight))
  const lines: PdfTextRecord[][] = []

  for (const record of records) {
    const current = lines.at(-1)
    const previous = current?.at(-1)
    const baselineTolerance = Math.max(2, Math.min(previous?.height ?? record.height, record.height) * 0.55)
    const baselineMatches = Boolean(previous && Math.abs(previous.baseline - record.baseline) <= baselineTolerance)
    const gap = previous ? record.x - (previous.x + previous.width) : 0
    const possibleColumnJump = gap > Math.max(72, record.height * 10)
    if (!current || previous?.item.hasEOL || !baselineMatches || possibleColumnJump) {
      lines.push([record])
    } else {
      current.push(record)
    }
  }

  return lines.map((line) => {
    const first = line[0]
    const text = line.map((record, index) => index === 0 ? record.item.str : `${textSeparator(line[index - 1], record)}${record.item.str}`).join('').trim()
    const fontNames = line.map((record) => record.item.fontName).filter((fontName): fontName is string => Boolean(fontName))
    const fontFamily = fontNames.map((fontName) => styles?.[fontName]?.fontFamily).find(Boolean)
    const fontSize = Math.max(...line.map((record) => record.fontSize))
    const style = `${safeFontFamily(fontFamily)}font-size:${round(fontSize)}px;line-height:1.4;`
    return {
      kind: 'text' as const,
      x: Math.min(...line.map((record) => record.x)),
      top: Math.min(...line.map((record) => record.top)),
      width: Math.max(...line.map((record) => record.x + record.width)) - Math.min(...line.map((record) => record.x)),
      height: Math.max(...line.map((record) => record.bottom)) - Math.min(...line.map((record) => record.top)),
      bottom: Math.max(...line.map((record) => record.bottom)),
      sourceOrder: first.order,
      fontSize,
      html: `<p style="${style}">${escapePdfHtml(text)}</p>`,
    }
  })
}

export function createPdfImageBlock(
  clientId: string,
  transform: number[],
  pageHeight: number,
  sourceOrder: number,
  rect: { x?: number; y?: number; width?: number; height?: number } = {},
): PdfLayoutBlock {
  const bounds = rectBounds(
    transform,
    Math.max(0.01, rect.width ?? 1),
    Math.max(0.01, rect.height ?? 1),
    pageHeight,
    rect.x ?? 0,
    rect.y ?? 0,
  )
  return { kind: 'image', clientId, sourceOrder, ...bounds }
}

/**
 * A dense grid or a scanned/vector page is more faithfully represented by one
 * rendered page image than by hundreds of unstructured text fragments.
 */
export function shouldRasterizePdfPage(complexity: PdfPageComplexity) {
  if (complexity.rotation && Math.abs(complexity.rotation) % 360 !== 0) return true
  if (complexity.textItemCount === 0) return complexity.imageCount > 0 || complexity.pathCount > 0
  return complexity.textItemCount >= 300 && complexity.pathCount >= 250
}

function clusterColumns(blocks: PdfLayoutBlock[], pageWidth: number): PdfColumn[] {
  const candidates = blocks
    .filter((block) => block.kind === 'text' && block.width < pageWidth * 0.55)
    .sort((left, right) => left.x - right.x)
  if (candidates.length < 6) return []
  const distance = Math.max(24, pageWidth * 0.035)
  const clusters: PdfLayoutBlock[][] = []
  for (const block of candidates) {
    const previous = clusters.at(-1)
    const previousCenter = previous && previous.reduce((sum, item) => sum + item.x, 0) / previous.length
    if (!previous || block.x - previousCenter! > distance) clusters.push([block])
    else previous.push(block)
  }
  const meaningful = clusters.filter((cluster) => cluster.length >= 3)
  if (meaningful.length < 2) return []

  const centers = meaningful.map((cluster) => cluster.reduce((sum, block) => sum + block.x, 0) / cluster.length)
  const assign = (block: PdfLayoutBlock) => {
    let closest = 0
    let distanceToClosest = Number.POSITIVE_INFINITY
    centers.forEach((center, index) => {
      const distanceToCenter = Math.abs((block.x + block.width / 2) - center)
      if (distanceToCenter < distanceToClosest) {
        closest = index
        distanceToClosest = distanceToCenter
      }
    })
    return closest
  }
  const sourceBlocks = blocks.filter((block) => block.kind === 'text').sort((left, right) => left.sourceOrder - right.sourceOrder)
  const runs: number[] = []
  let previousColumn = -1
  for (const block of sourceBlocks) {
    const column = assign(block)
    if (column !== previousColumn) runs.push(1)
    else runs[runs.length - 1] += 1
    previousColumn = column
  }
  const longRuns = runs.filter((length) => length >= 3).length
  if (longRuns < meaningful.length || runs.length > meaningful.length * 2 + 1) return []
  return centers.map((center) => ({ center }))
}

function isPageAnchor(block: PdfLayoutBlock, pageWidth: number, pageHeight: number) {
  return block.width >= pageWidth * 0.55 || block.top <= pageHeight * 0.08 || block.bottom >= pageHeight * 0.92
}

function sortSimple(blocks: PdfLayoutBlock[]) {
  return [...blocks].sort((left, right) => left.top - right.top || left.x - right.x || left.sourceOrder - right.sourceOrder)
}

/** Return blocks in a reading order that handles page anchors and continuous multi-column regions. */
export function orderPdfBlocks(blocks: readonly PdfLayoutBlock[], pageWidth: number, pageHeight: number): PdfLayoutBlock[] {
  const visible = blocks.filter((block) => block.width > 0 && block.height > 0)
  const columns = clusterColumns([...visible], pageWidth)
  if (columns.length < 2) return sortSimple([...visible])

  const anchors = visible.filter((block) => isPageAnchor(block, pageWidth, pageHeight)).sort((left, right) => left.top - right.top || left.sourceOrder - right.sourceOrder)
  const body = visible.filter((block) => !isPageAnchor(block, pageWidth, pageHeight))
  const assignColumn = (block: PdfLayoutBlock) => {
    const center = block.x + block.width / 2
    return columns.reduce((best, column, index) => Math.abs(columns[best].center - center) <= Math.abs(column.center - center) ? best : index, 0)
  }
  const orderBody = (from: number, to: number) => {
    const segment = body.filter((block) => block.top >= from - 2 && block.top < to - 2)
    const result: PdfLayoutBlock[] = []
    columns.forEach((_column, index) => {
      result.push(...segment.filter((block) => assignColumn(block) === index).sort((left, right) => left.top - right.top || left.sourceOrder - right.sourceOrder))
    })
    return result
  }

  const result: PdfLayoutBlock[] = []
  let cursor = 0
  for (const anchor of anchors) {
    result.push(...orderBody(cursor, anchor.top))
    result.push(anchor)
    cursor = Math.max(cursor, anchor.bottom)
  }
  result.push(...orderBody(cursor, pageHeight + 1))
  return result
}

function imageTag(block: PdfLayoutBlock, pageWidth: number) {
  const widthPercent = Math.min(100, Math.max(1, (block.width / pageWidth) * 100))
  const widthStyle = widthPercent < 98 ? `width:${round(widthPercent)}%;` : ''
  return `<img src="direct-import://asset/${escapePdfHtml(block.clientId ?? '')}" alt="图片" style="display:block;${widthStyle}max-width:100%;height:auto;box-sizing:border-box;" />`
}

function sameImageRow(left: PdfLayoutBlock, right: PdfLayoutBlock, pageWidth: number) {
  const overlap = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top)
  const minHeight = Math.min(left.height, right.height)
  const horizontalGap = right.x - (left.x + left.width)
  return overlap >= minHeight * 0.45 && horizontalGap <= Math.max(32, pageWidth * 0.04)
}

/** Render image blocks with intrinsic width and preserve adjacent images as a responsive flex row. */
export function renderPdfBlocks(blocks: readonly PdfLayoutBlock[], pageWidth: number) {
  const html: string[] = []
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index]
    if (block.kind === 'text') {
      if (block.html) html.push(block.html)
      continue
    }
    const row = [block]
    while (index + row.length < blocks.length) {
      const next = blocks[index + row.length]
      if (next.kind !== 'image' || !sameImageRow(row.at(-1)!, next, pageWidth)) break
      row.push(next)
    }
    index += row.length - 1
    if (row.length === 1) {
      html.push(`<p style="margin:0 0 1em;">${imageTag(block, pageWidth)}</p>`)
    } else {
      html.push(`<div style="display:flex;flex-wrap:wrap;align-items:flex-start;gap:12px;margin:0 0 1em;">${row.map((item) => `<div style="flex:0 1 ${round(Math.min(100, Math.max(1, (item.width / pageWidth) * 100)))}%;min-width:0;max-width:100%;">${imageTag({ ...item, width: pageWidth }, pageWidth)}</div>`).join('')}</div>`)
    }
  }
  return html.join('\n')
}
