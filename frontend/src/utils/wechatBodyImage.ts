export const WECHAT_PERMANENT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
// Kept as a compatibility alias for existing upload callers.
export const WECHAT_BODY_IMAGE_MAX_BYTES = WECHAT_PERMANENT_IMAGE_MAX_BYTES

const WECHAT_PERMANENT_IMAGE_TARGET_BYTES = WECHAT_PERMANENT_IMAGE_MAX_BYTES - 8 * 1024
const MAX_IMAGE_DIMENSION = 4096
const MIN_IMAGE_DIMENSION = 320
const MIN_JPEG_QUALITY = 0.4
const MAX_RESIZE_ATTEMPTS = 7
const WECHAT_PERMANENT_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/bmp'])

export interface PreparedWeChatBodyImage {
  file: File
  wasCompressed: boolean
  originalSize: number
}

export function formatWeChatImageSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function jpegFilename(filename: string): string {
  const stem = filename.replace(/\.[^./\\]+$/, '').trim() || 'image'
  return `${stem}.jpg`
}

async function gifDimensions(file: File): Promise<{ width: number; height: number } | null> {
  // GIF logical screen width and height are little-endian bytes 6 through 9.
  const bytes = new Uint8Array(await file.slice(0, 10).arrayBuffer())
  if (bytes.length < 10 || String.fromCharCode(...bytes.slice(0, 3)) !== 'GIF') return null
  return {
    width: bytes[6] | (bytes[7] << 8),
    height: bytes[8] | (bytes[9] << 8),
  }
}

function readImage(blob: Blob): Promise<HTMLImageElement> {
  const objectUrl = URL.createObjectURL(blob)
  return new Promise((resolve, reject) => {
    const image = new Image()
    const cleanup = () => URL.revokeObjectURL(objectUrl)
    image.onload = () => {
      cleanup()
      resolve(image)
    }
    image.onerror = () => {
      cleanup()
      reject(new Error('浏览器无法读取这张图片，无法在本地压缩'))
    }
    image.src = objectUrl
  })
}

function canvasToJpeg(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('浏览器无法编码压缩后的图片'))
    }, 'image/jpeg', quality)
  })
}

async function encodeWithinLimit(canvas: HTMLCanvasElement): Promise<Blob | null> {
  let lowerQuality = MIN_JPEG_QUALITY
  let upperQuality = 0.92
  let best: Blob | null = null

  for (let attempt = 0; attempt < 7; attempt += 1) {
    const quality = (lowerQuality + upperQuality) / 2
    const blob = await canvasToJpeg(canvas, quality)
    if (blob.size <= WECHAT_PERMANENT_IMAGE_TARGET_BYTES) {
      best = blob
      lowerQuality = quality
    } else {
      upperQuality = quality
    }
  }
  return best
}

async function compressStaticImageToJpeg(file: File): Promise<PreparedWeChatBodyImage> {
  const image = await readImage(file)
  const sourceWidth = image.naturalWidth || image.width
  const sourceHeight = image.naturalHeight || image.height
  if (!sourceWidth || !sourceHeight) throw new Error('图片尺寸无效，无法在本地压缩')

  const initialScale = Math.min(1, MAX_IMAGE_DIMENSION / Math.max(sourceWidth, sourceHeight))
  let width = Math.max(1, Math.round(sourceWidth * initialScale))
  let height = Math.max(1, Math.round(sourceHeight * initialScale))
  const canvas = document.createElement('canvas')

  for (let attempt = 0; attempt < MAX_RESIZE_ATTEMPTS; attempt += 1) {
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器不支持图片压缩')
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, width, height)
    context.drawImage(image, 0, 0, width, height)

    const compressed = await encodeWithinLimit(canvas)
    if (compressed) {
      return {
        file: new File([compressed], jpegFilename(file.name), { type: 'image/jpeg', lastModified: file.lastModified }),
        wasCompressed: true,
        originalSize: file.size,
      }
    }

    const nextWidth = Math.max(MIN_IMAGE_DIMENSION, Math.round(width * 0.75))
    const nextHeight = Math.max(MIN_IMAGE_DIMENSION, Math.round(height * 0.75))
    if (nextWidth === width && nextHeight === height) break
    width = nextWidth
    height = nextHeight
  }
  throw new Error('图片无法压缩到公众号永久素材要求的 10 MB 以内，请更换图片')
}

async function compressTransparentPng(file: File): Promise<PreparedWeChatBodyImage> {
  const { optimise } = await import('@jsquash/oxipng')
  const optimized = await optimise(await file.arrayBuffer(), { level: 4, optimiseAlpha: false })
  if (optimized.byteLength > WECHAT_PERMANENT_IMAGE_TARGET_BYTES) {
    throw new Error('透明 PNG 无法在不改变透明效果的前提下压缩到公众号要求的 10 MB 以内，请更换图片')
  }
  return {
    file: new File([optimized], file.name || 'image.png', { type: 'image/png', lastModified: file.lastModified }),
    wasCompressed: true,
    originalSize: file.size,
  }
}

async function compressGif(file: File): Promise<PreparedWeChatBodyImage> {
  const { default: gifsicle } = await import('gifsicle-wasm-browser')
  const dimensions = await gifDimensions(file)
  const resize = dimensions && dimensions.width > 0 && dimensions.height > 0
    ? ` --resize ${Math.max(1, Math.round(dimensions.width * 0.8))}x${Math.max(1, Math.round(dimensions.height * 0.8))}`
    : ''
  const commands = [
    '-O1 --lossy=40 input.gif -o /out/output.gif',
    '-O2 --lossy=80 input.gif -o /out/output.gif',
    `-O2 --lossy=120${resize} input.gif -o /out/output.gif`,
    `-O2 --lossy=180${resize} input.gif -o /out/output.gif`,
  ]

  for (const command of commands) {
    const files = await gifsicle.run({
      input: [{ file, name: 'input.gif' }],
      command: [command],
      isStrict: true,
    })
    const output = files.at(-1)
    if (output && output.size <= WECHAT_PERMANENT_IMAGE_TARGET_BYTES) {
      return {
        file: new File([output], file.name || 'image.gif', { type: 'image/gif', lastModified: file.lastModified }),
        wasCompressed: true,
        originalSize: file.size,
      }
    }
  }
  throw new Error('GIF 无法在保留动效的前提下压缩到公众号要求的 10 MB 以内，请更换图片')
}

/**
 * Preserves native WeChat-compatible image formats so transparent PNGs and GIF
 * animations reach the permanent-material API unchanged. Unsupported formats
 * are converted when users upload them from the browser.
 */
export async function prepareWeChatBodyImage(file: File): Promise<PreparedWeChatBodyImage> {
  const contentType = file.type.toLowerCase()
  if (!contentType.startsWith('image/')) throw new Error('只能处理图片文件')
  if (WECHAT_PERMANENT_IMAGE_TYPES.has(contentType) && file.size <= WECHAT_PERMANENT_IMAGE_MAX_BYTES) {
    return { file, wasCompressed: false, originalSize: file.size }
  }
  if (contentType === 'image/gif') return compressGif(file)
  if (contentType === 'image/png') return compressTransparentPng(file)
  if (contentType === 'image/bmp') {
    throw new Error('BMP 图片超过公众号永久素材要求的 10 MB，请更换图片')
  }
  return compressStaticImageToJpeg(file)
}
