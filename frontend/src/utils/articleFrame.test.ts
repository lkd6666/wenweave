import { describe, expect, it } from 'vitest'
import { ARTICLE_RENDER_CSS, ARTICLE_RENDER_ROOT_CLASS, ARTICLE_RENDER_VIEWPORT } from './articleFrame'

describe('article rendering baseline', () => {
  it('preserves the native table formatting context used by the editor canvas', () => {
    expect(ARTICLE_RENDER_CSS).toContain(`.${ARTICLE_RENDER_ROOT_CLASS} table { max-width: 100%; }`)
    expect(ARTICLE_RENDER_CSS).not.toMatch(/table\s*\{[^}]*display\s*:\s*block/s)
  })

  it('keeps the canvas viewport and content box stable on mobile', () => {
    expect(ARTICLE_RENDER_VIEWPORT).toBe('width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no')
    expect(ARTICLE_RENDER_CSS).toContain('padding: 16px 12px 32px;')
    expect(ARTICLE_RENDER_CSS).toContain('box-sizing: border-box;')
  })
})
