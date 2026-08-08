export const CROP_RECT_SCALE = 100_000
const JPEG_CROP_QUALITY = 0.92

export interface CropRect {
  x: number
  y: number
  width: number
  height: number
}

export class ImageCropError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ImageCropError'
  }
}

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value))

export const FULL_CROP_RECT: CropRect = {
  x: 0,
  y: 0,
  width: CROP_RECT_SCALE,
  height: CROP_RECT_SCALE,
}

export function normalizeCropRect(value: Partial<CropRect> | null | undefined): CropRect | null {
  if (!value) return null
  const x = Math.round(Number(value.x))
  const y = Math.round(Number(value.y))
  const width = Math.round(Number(value.width))
  const height = Math.round(Number(value.height))
  if (![x, y, width, height].every(Number.isFinite)) return null

  const normalizedX = clamp(x, 0, CROP_RECT_SCALE)
  const normalizedY = clamp(y, 0, CROP_RECT_SCALE)
  const normalizedWidth = clamp(width, 0, CROP_RECT_SCALE - normalizedX)
  const normalizedHeight = clamp(height, 0, CROP_RECT_SCALE - normalizedY)
  if (normalizedWidth <= 0 || normalizedHeight <= 0) return null
  return { x: normalizedX, y: normalizedY, width: normalizedWidth, height: normalizedHeight }
}

export function parseCropRect(value: string | null | undefined): CropRect | null {
  if (!value) return null
  const [x, y, width, height, ...unexpected] = value.split(',').map((item) => Number(item.trim()))
  if (unexpected.length > 0) return null
  return normalizeCropRect({ x, y, width, height })
}

export function serializeCropRect(rect: CropRect): string {
  const normalized = normalizeCropRect(rect)
  if (!normalized) throw new ImageCropError('裁剪范围无效')
  return [normalized.x, normalized.y, normalized.width, normalized.height].join(',')
}

export function isFullCropRect(rect: CropRect | null | undefined): boolean {
  const normalized = normalizeCropRect(rect)
  return Boolean(
    normalized
    && normalized.x === FULL_CROP_RECT.x
    && normalized.y === FULL_CROP_RECT.y
    && normalized.width === FULL_CROP_RECT.width
    && normalized.height === FULL_CROP_RECT.height,
  )
}

export function cropPercentagesToRect(value: { x: number; y: number; width: number; height: number }): CropRect | null {
  return normalizeCropRect({
    x: (value.x / 100) * CROP_RECT_SCALE,
    y: (value.y / 100) * CROP_RECT_SCALE,
    width: (value.width / 100) * CROP_RECT_SCALE,
    height: (value.height / 100) * CROP_RECT_SCALE,
  })
}

export function cropRectToPercentages(rect: CropRect): { x: number; y: number; width: number; height: number } {
  const normalized = normalizeCropRect(rect)
  if (!normalized) throw new ImageCropError('裁剪范围无效')
  return {
    x: (normalized.x / CROP_RECT_SCALE) * 100,
    y: (normalized.y / CROP_RECT_SCALE) * 100,
    width: (normalized.width / CROP_RECT_SCALE) * 100,
    height: (normalized.height / CROP_RECT_SCALE) * 100,
  }
}

export function wordSourceRectToCropRect(value: { left?: string | null; top?: string | null; right?: string | null; bottom?: string | null }): CropRect | null {
  const parseInset = (raw: string | null | undefined) => {
    if (raw === null || raw === undefined || raw === '') return 0
    const parsed = Number(raw)
    return Number.isFinite(parsed) ? clamp(Math.round(parsed), 0, CROP_RECT_SCALE) : null
  }
  const left = parseInset(value.left)
  const top = parseInset(value.top)
  const right = parseInset(value.right)
  const bottom = parseInset(value.bottom)
  if (left === null || top === null || right === null || bottom === null) return null
  return normalizeCropRect({
    x: left,
    y: top,
    width: CROP_RECT_SCALE - left - right,
    height: CROP_RECT_SCALE - top - bottom,
  })
}

function cropPixels(rect: CropRect, width: number, height: number) {
  const normalized = normalizeCropRect(rect)
  if (!normalized || width <= 0 || height <= 0) throw new ImageCropError('无法读取图片尺寸')
  const x = clamp(Math.round((normalized.x / CROP_RECT_SCALE) * width), 0, width - 1)
  const y = clamp(Math.round((normalized.y / CROP_RECT_SCALE) * height), 0, height - 1)
  const right = clamp(Math.round(((normalized.x + normalized.width) / CROP_RECT_SCALE) * width), x + 1, width)
  const bottom = clamp(Math.round(((normalized.y + normalized.height) / CROP_RECT_SCALE) * height), y + 1, height)
  return { x, y, width: right - x, height: bottom - y }
}

function cropOutputContentType(source: Blob): 'image/jpeg' | 'image/png' {
  const contentType = source.type.toLowerCase()
  return contentType === 'image/jpeg' || contentType === 'image/jpg' || contentType === 'image/bmp'
    ? 'image/jpeg'
    : 'image/png'
}

async function canvasToImageBlob(
  canvas: OffscreenCanvas | HTMLCanvasElement,
  contentType: 'image/jpeg' | 'image/png',
): Promise<Blob> {
  if ('convertToBlob' in canvas) {
    return canvas.convertToBlob({
      type: contentType,
      quality: contentType === 'image/jpeg' ? JPEG_CROP_QUALITY : undefined,
    })
  }
  const htmlCanvas = canvas as HTMLCanvasElement
  return new Promise<Blob>((resolve, reject) => {
    htmlCanvas.toBlob((blob: Blob | null) => {
      if (blob) resolve(blob)
      else reject(new ImageCropError('无法生成裁剪图片'))
    }, contentType, contentType === 'image/jpeg' ? JPEG_CROP_QUALITY : undefined)
  })
}

async function cropWithImageBitmap(source: Blob, rect: CropRect): Promise<Blob> {
  const bitmap = await createImageBitmap(source)
  try {
    const pixels = cropPixels(rect, bitmap.width, bitmap.height)
    const canvas = new OffscreenCanvas(pixels.width, pixels.height)
    const context = canvas.getContext('2d')
    if (!context) throw new ImageCropError('浏览器无法创建图片画布')
    context.drawImage(bitmap, pixels.x, pixels.y, pixels.width, pixels.height, 0, 0, pixels.width, pixels.height)
    return canvasToImageBlob(canvas, cropOutputContentType(source))
  } finally {
    bitmap.close()
  }
}

async function cropWithHtmlImage(source: Blob, rect: CropRect): Promise<Blob> {
  if (typeof document === 'undefined') throw new ImageCropError('当前浏览器不支持图片裁剪')
  const url = URL.createObjectURL(source)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new ImageCropError('无法解码原图'))
      element.src = url
    })
    const pixels = cropPixels(rect, image.naturalWidth, image.naturalHeight)
    const canvas = document.createElement('canvas')
    canvas.width = pixels.width
    canvas.height = pixels.height
    const context = canvas.getContext('2d')
    if (!context) throw new ImageCropError('浏览器无法创建图片画布')
    context.drawImage(image, pixels.x, pixels.y, pixels.width, pixels.height, 0, 0, pixels.width, pixels.height)
    return canvasToImageBlob(canvas, cropOutputContentType(source))
  } finally {
    URL.revokeObjectURL(url)
  }
}

export async function cropImageBlob(source: Blob, rect: CropRect): Promise<Blob> {
  if (source.type.toLowerCase() === 'image/gif') throw new ImageCropError('暂不支持裁剪 GIF 动图')
  let result: Blob
  try {
    if (typeof createImageBitmap === 'function' && typeof OffscreenCanvas !== 'undefined') {
      result = await cropWithImageBitmap(source, rect)
    } else {
      result = await cropWithHtmlImage(source, rect)
    }
  } catch (error) {
    if (error instanceof ImageCropError) throw error
    throw new ImageCropError('无法解码原图或生成裁剪图片')
  }
  return result
}
