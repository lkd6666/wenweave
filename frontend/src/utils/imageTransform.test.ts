import { describe, expect, it } from 'vitest'
import {
  pdfImageDisplayAspectRatio,
  pdfMatrixToImageTransform,
  transformedImageDisplaySize,
} from './imageTransform'

describe('image transforms', () => {
  it('derives PDF image rotation and its visual aspect ratio from the graphics matrix', () => {
    const matrix = [0, 50, -100, 0, 0, 0]

    expect(pdfMatrixToImageTransform(matrix)).toEqual({ rotationDegrees: 90 })
    expect(pdfImageDisplayAspectRatio(matrix)).toBeCloseTo(2)
  })

  it('keeps the rotated Word image layout box in sync with its baked pixels', () => {
    expect(transformedImageDisplaySize(192, 96, { rotationDegrees: 90 })).toMatchObject({ width: expect.closeTo(96), height: expect.closeTo(192) })
    expect(transformedImageDisplaySize(192, 96, { rotationDegrees: -90 })).toMatchObject({ width: expect.closeTo(96), height: expect.closeTo(192) })
  })

  it('retains a PDF reflection alongside its orientation', () => {
    expect(pdfMatrixToImageTransform([100, 0, 0, -50, 0, 0])).toEqual({ flipVertical: true })
  })
})
