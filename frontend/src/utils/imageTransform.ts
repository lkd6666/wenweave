const JPEG_QUALITY = 0.92
const TRANSFORM_EPSILON = 0.001

export interface RasterImageTransform {
  rotationDegrees?: number
  flipHorizontal?: boolean
  flipVertical?: boolean
}

export class ImageTransformError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ImageTransformError'
  }
}

export function normalizeImageRotationDegrees(value: number | null | undefined): number {
  if (!Number.isFinite(value)) return 0
  const normalized = (((Number(value) + 180) % 360) + 360) % 360 - 180
  return Math.abs(normalized) < TRANSFORM_EPSILON ? 0 : normalized
}

export function hasRasterImageTransform(transform: RasterImageTransform | null | undefined): boolean {
  return Boolean(transform?.flipHorizontal || transform?.flipVertical || Math.abs(normalizeImageRotationDegrees(transform?.rotationDegrees)) >= TRANSFORM_EPSILON)
}

export function rasterImageTransformKey(transform: RasterImageTransform | null | undefined): string {
  const rotation = normalizeImageRotationDegrees(transform?.rotationDegrees)
  return `${Math.round(rotation * 1000) / 1000}:${transform?.flipHorizontal ? 'flip-h' : 'plain'}:${transform?.flipVertical ? 'flip-v' : 'plain'}`
}

export function transformedImageDisplaySize(
  width: number,
  height: number,
  transform: RasterImageTransform | null | undefined,
): { width: number; height: number } {
  const rotation = Math.abs(normalizeImageRotationDegrees(transform?.rotationDegrees)) * Math.PI / 180
  const cosine = Math.abs(Math.cos(rotation))
  const sine = Math.abs(Math.sin(rotation))
  return {
    width: cosine * width + sine * height,
    height: sine * width + cosine * height,
  }
}

/** Extract the orientation portion of a PDF graphics-state matrix. */
export function pdfMatrixToImageTransform(matrix: readonly number[]): RasterImageTransform {
  const [a = 1, b = 0, c = 0, d = 1] = matrix.map(Number)
  const xAxisLength = Math.hypot(a, b)
  if (!Number.isFinite(xAxisLength) || xAxisLength < TRANSFORM_EPSILON) return {}
  const rotationDegrees = normalizeImageRotationDegrees(Math.atan2(b, a) * 180 / Math.PI)
  const determinant = a * d - b * c
  return {
    ...(rotationDegrees ? { rotationDegrees } : {}),
    ...(Number.isFinite(determinant) && determinant < 0 ? { flipVertical: true } : {}),
  }
}

/** Return the aspect ratio of a PDF image after its graphics-state matrix is applied. */
export function pdfImageDisplayAspectRatio(
  matrix: readonly number[],
  sourceWidth = 1,
  sourceHeight = 1,
): number | undefined {
  const [a = 1, b = 0, c = 0, d = 1] = matrix.map(Number)
  const width = Math.abs(a) * Math.max(0.01, sourceWidth) + Math.abs(c) * Math.max(0.01, sourceHeight)
  const height = Math.abs(b) * Math.max(0.01, sourceWidth) + Math.abs(d) * Math.max(0.01, sourceHeight)
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0 ? width / height : undefined
}

function outputContentType(source: Blob): 'image/jpeg' | 'image/png' {
  const type = source.type.toLowerCase()
  return type === 'image/jpeg' || type === 'image/jpg' || type === 'image/bmp' ? 'image/jpeg' : 'image/png'
}

function outputDimensions(width: number, height: number, rotationDegrees: number) {
  return transformedImageDisplaySize(width, height, { rotationDegrees })
}

function resizedDimensions(width: number, height: number, aspectRatio: number | undefined) {
  if (!Number.isFinite(aspectRatio) || !aspectRatio || aspectRatio <= 0) return { width, height }
  const area = Math.max(1, width * height)
  const resizedWidth = Math.max(1, Math.round(Math.sqrt(area * aspectRatio)))
  return { width: resizedWidth, height: Math.max(1, Math.round(resizedWidth / aspectRatio)) }
}

async function canvasToBlob(canvas: OffscreenCanvas, contentType: 'image/jpeg' | 'image/png'): Promise<Blob> {
  return canvas.convertToBlob({
    type: contentType,
    quality: contentType === 'image/jpeg' ? JPEG_QUALITY : undefined,
  })
}

function drawImageTransform(
  canvas: OffscreenCanvas,
  image: ImageBitmap | OffscreenCanvas,
  sourceWidth: number,
  sourceHeight: number,
  transform: RasterImageTransform,
  contentType: 'image/jpeg' | 'image/png',
) {
  const context = canvas.getContext('2d')
  if (!context) throw new ImageTransformError('浏览器无法创建图片画布')
  if (contentType === 'image/jpeg') {
    context.fillStyle = '#fff'
    context.fillRect(0, 0, canvas.width, canvas.height)
  }
  context.translate(canvas.width / 2, canvas.height / 2)
  context.rotate(normalizeImageRotationDegrees(transform.rotationDegrees) * Math.PI / 180)
  context.scale(transform.flipHorizontal ? -1 : 1, transform.flipVertical ? -1 : 1)
  context.drawImage(image, -sourceWidth / 2, -sourceHeight / 2, sourceWidth, sourceHeight)
}

/**
 * Bake a supported image rotation/reflection into pixels so downstream HTML and
 * publishing targets do not need CSS transforms to display it correctly.
 */
export async function transformImageBlob(
  source: Blob,
  transform: RasterImageTransform,
  options: { outputAspectRatio?: number } = {},
): Promise<Blob> {
  if (!hasRasterImageTransform(transform)) return source
  if (source.type.toLowerCase() === 'image/gif') throw new ImageTransformError('暂不支持变换 GIF 动图')
  if (typeof createImageBitmap !== 'function' || typeof OffscreenCanvas === 'undefined') {
    throw new ImageTransformError('当前浏览器不支持图片旋转')
  }

  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(source)
  } catch {
    throw new ImageTransformError('无法解码原图')
  }
  try {
    const contentType = outputContentType(source)
    const transformedSize = outputDimensions(bitmap.width, bitmap.height, transform.rotationDegrees ?? 0)
    const rotatedCanvas = new OffscreenCanvas(Math.max(1, Math.ceil(transformedSize.width)), Math.max(1, Math.ceil(transformedSize.height)))
    drawImageTransform(rotatedCanvas, bitmap, bitmap.width, bitmap.height, transform, contentType)

    const targetSize = resizedDimensions(rotatedCanvas.width, rotatedCanvas.height, options.outputAspectRatio)
    if (targetSize.width === rotatedCanvas.width && targetSize.height === rotatedCanvas.height) {
      return canvasToBlob(rotatedCanvas, contentType)
    }
    const outputCanvas = new OffscreenCanvas(targetSize.width, targetSize.height)
    const outputContext = outputCanvas.getContext('2d')
    if (!outputContext) throw new ImageTransformError('浏览器无法创建图片画布')
    if (contentType === 'image/jpeg') {
      outputContext.fillStyle = '#fff'
      outputContext.fillRect(0, 0, outputCanvas.width, outputCanvas.height)
    }
    outputContext.drawImage(rotatedCanvas, 0, 0, outputCanvas.width, outputCanvas.height)
    return canvasToBlob(outputCanvas, contentType)
  } finally {
    bitmap.close()
  }
}
