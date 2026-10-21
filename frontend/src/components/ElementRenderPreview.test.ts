import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Window } from 'happy-dom'
import { extractImagePreview } from '../utils/elementImagePreview'

describe('extractImagePreview', () => {
  beforeEach(() => vi.stubGlobal('DOMParser', new Window().DOMParser))
  afterEach(() => vi.unstubAllGlobals())

  it('previews a normal image from src', () => {
    expect(extractImagePreview('<img src="photo.png" alt="照片">')).toEqual({ src: 'photo.png', alt: '照片' })
  })

  it('previews a standalone SVG image from href', () => {
    expect(extractImagePreview('<image href="photo.png" title="实验室"></image>')).toEqual({ src: 'photo.png', alt: '实验室' })
  })

  it('uses xlink:href when href is empty', () => {
    expect(extractImagePreview('<image href="" xlink:href="legacy.png" />')).toEqual({ src: 'legacy.png', alt: '' })
  })

  it('prefers href when both SVG source attributes are present', () => {
    expect(extractImagePreview('<image href="new.png" xlink:href="old.png" />')?.src).toBe('new.png')
  })

  it('does not treat a larger element as a single image', () => {
    expect(extractImagePreview('<section><img src="photo.png"></section>')).toBeNull()
  })
})
