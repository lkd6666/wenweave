import { describe, expect, it } from 'vitest'
import {
  getStoragePreviewKind,
  needsStoragePreviewFetch,
  STORAGE_PREVIEW_FETCH_LIMIT_BYTES,
} from './storagePreview'

describe('storage preview type detection', () => {
  it.each([
    ['report.PDF', 'pdf'],
    ['brief.DOCX', 'docx'],
    ['notes.Md', 'markdown'],
    ['readme.TXT', 'text'],
    ['cover.webp', 'image'],
    ['clip.webm', 'video'],
    ['legacy.doc', 'other'],
    ['slides.pptx', 'other'],
  ] as const)('maps %s to %s', (filename, expected) => {
    expect(getStoragePreviewKind(filename)).toBe(expected)
  })

  it('only fetches complete content for browser-rendered document types', () => {
    expect(needsStoragePreviewFetch('pdf')).toBe(true)
    expect(needsStoragePreviewFetch('docx')).toBe(true)
    expect(needsStoragePreviewFetch('markdown')).toBe(true)
    expect(needsStoragePreviewFetch('text')).toBe(true)
    expect(needsStoragePreviewFetch('other')).toBe(false)
    expect(STORAGE_PREVIEW_FETCH_LIMIT_BYTES).toBe(50 * 1024 * 1024)
  })
})
