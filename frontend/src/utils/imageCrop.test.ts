import { describe, expect, it } from 'vitest'
import {
  CROP_RECT_SCALE,
  FULL_CROP_RECT,
  cropPercentagesToRect,
  isFullCropRect,
  parseCropRect,
  serializeCropRect,
  wordSourceRectToCropRect,
} from './imageCrop'

describe('image crop metadata', () => {
  it('converts DrawingML insets into a retained source rectangle', () => {
    expect(wordSourceRectToCropRect({ left: '10000', top: '20000', right: '30000', bottom: '40000' })).toEqual({
      x: 10000,
      y: 20000,
      width: 60000,
      height: 40000,
    })
  })

  it('rejects invalid or empty source rectangles', () => {
    expect(wordSourceRectToCropRect({ left: '60000', right: '50000' })).toBeNull()
    expect(wordSourceRectToCropRect({ left: 'bad-value' })).toBeNull()
  })

  it('round-trips persisted crop metadata', () => {
    const rect = cropPercentagesToRect({ x: 12.5, y: 10, width: 75, height: 80 })
    expect(rect).toEqual({ x: 12500, y: 10000, width: 75000, height: 80000 })
    expect(parseCropRect(serializeCropRect(rect!))).toEqual(rect)
    expect(isFullCropRect(FULL_CROP_RECT)).toBe(true)
    expect(isFullCropRect({ x: 0, y: 0, width: CROP_RECT_SCALE - 1, height: CROP_RECT_SCALE })).toBe(false)
  })
})
