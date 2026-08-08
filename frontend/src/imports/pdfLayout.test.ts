import { describe, expect, it } from 'vitest'
import {
  buildPdfTextBlocks,
  createPdfImageBlock,
  orderPdfBlocks,
  renderPdfBlocks,
  shouldRasterizePdfPage,
} from './pdfLayout'

const text = (str: string, x: number, y: number, options: { width?: number; hasEOL?: boolean } = {}) => ({
  str,
  transform: [12, 0, 0, 12, x, y],
  width: options.width ?? str.length * 6,
  height: 12,
  hasEOL: options.hasEOL,
})

describe('pdf layout reconstruction', () => {
  it('merges fragmented text and inserts a space only when geometry needs one', () => {
    const blocks = buildPdfTextBlocks([
      text('Hello', 50, 740, { width: 30 }),
      text('world', 86, 740, { width: 30, hasEOL: true }),
      text('下一行', 50, 720, { width: 36, hasEOL: true }),
    ], undefined, 800)

    expect(blocks).toHaveLength(2)
    expect(blocks[0].html).toContain('Hello world')
    expect(blocks[1].html).toContain('下一行')
  })

  it('keeps continuous two-column content in column order and leaves header/footer at page edges', () => {
    const items = [
      text('Header', 50, 760, { width: 42, hasEOL: true }),
      ...Array.from({ length: 5 }, (_, index) => text(`left-${index + 1}`, 50, 720 - index * 30, { width: 42, hasEOL: true })),
      ...Array.from({ length: 5 }, (_, index) => text(`right-${index + 1}`, 320, 720 - index * 30, { width: 48, hasEOL: true })),
      text('Footer', 50, 40, { width: 36, hasEOL: true }),
    ]
    const blocks = buildPdfTextBlocks(items, undefined, 800)
    const ordered = orderPdfBlocks(blocks, 600, 800)
    const html = ordered.map((block) => block.html).join(' ')

    expect(html.indexOf('Header')).toBeLessThan(html.indexOf('left-1'))
    expect(html.indexOf('left-5')).toBeLessThan(html.indexOf('right-1'))
    expect(html.indexOf('right-5')).toBeLessThan(html.indexOf('Footer'))
  })

  it('uses transformed image bounds and keeps adjacent images in one responsive row', () => {
    const blocks = [
      createPdfImageBlock('a', [100, 0, 0, 80, 50, 500], 800, 0),
      createPdfImageBlock('b', [100, 0, 0, 80, 160, 500], 800, 1),
    ]
    expect(blocks[0]).toMatchObject({ x: 50, width: 100, height: 80, top: 220, bottom: 300 })
    const html = renderPdfBlocks(orderPdfBlocks(blocks, 600, 800), 600)
    expect(html).toContain('display:flex')
    expect(html).toContain('direct-import://asset/a')
    expect(html).toContain('direct-import://asset/b')
  })

  it('does not turn row-wise table cells into column-wise reading order', () => {
    const items = Array.from({ length: 4 }, (_, row) => [
      text(`r${row + 1}c1`, 40, 700 - row * 24, { width: 32, hasEOL: false }),
      text(`r${row + 1}c2`, 200, 700 - row * 24, { width: 32, hasEOL: false }),
      text(`r${row + 1}c3`, 360, 700 - row * 24, { width: 32, hasEOL: true }),
    ]).flat()
    const blocks = buildPdfTextBlocks(items, undefined, 800)
    const html = orderPdfBlocks(blocks, 600, 800).map((block) => block.html).join(' ')
    expect(html.indexOf('r1c3')).toBeLessThan(html.indexOf('r2c1'))
    expect(html.indexOf('r2c3')).toBeLessThan(html.indexOf('r3c1'))
  })

  it('calculates a sane font size for rotated text', () => {
    const blocks = buildPdfTextBlocks([{
      str: 'rotated',
      transform: [0, 12, -12, 0, 100, 700],
      width: 42,
      height: 12,
      hasEOL: true,
    }], undefined, 800)
    expect(blocks[0].fontSize).toBe(12)
    expect(blocks[0].height).toBeGreaterThan(blocks[0].fontSize ?? 0)
  })

  it('uses raster fallback only for scanned or dense grid pages', () => {
    expect(shouldRasterizePdfPage({ textItemCount: 0, imageCount: 1, pathCount: 0 })).toBe(true)
    expect(shouldRasterizePdfPage({ textItemCount: 659, imageCount: 0, pathCount: 460 })).toBe(true)
    expect(shouldRasterizePdfPage({ textItemCount: 576, imageCount: 0, pathCount: 40 })).toBe(false)
    expect(shouldRasterizePdfPage({ textItemCount: 20, imageCount: 0, pathCount: 0 })).toBe(false)
    expect(shouldRasterizePdfPage({ textItemCount: 20, imageCount: 0, pathCount: 0, rotation: 90 })).toBe(true)
  })
})
