export const WECHAT_PERMANENT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
// Kept as a compatibility alias for existing upload callers.
export const WECHAT_BODY_IMAGE_MAX_BYTES = WECHAT_PERMANENT_IMAGE_MAX_BYTES

const WECHAT_PERMANENT_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/bmp'])

export interface PreparedWeChatBodyImage {
  file: File
  wasCompressed: false
  originalSize: number
}

/**
 * Validate images for WeChat without changing their bytes, format, colour
 * profile, dimensions, transparency, or GIF animation.
 */
export async function prepareWeChatBodyImage(file: File): Promise<PreparedWeChatBodyImage> {
  const contentType = file.type.toLowerCase()
  if (!contentType.startsWith('image/')) throw new Error('只能处理图片文件')
  if (!WECHAT_PERMANENT_IMAGE_TYPES.has(contentType)) {
    throw new Error('公众号正文仅支持 JPG、PNG、GIF 或 BMP；为保留原图，不会自动转换格式')
  }
  if (file.size > WECHAT_PERMANENT_IMAGE_MAX_BYTES) {
    throw new Error('图片超过公众号永久素材 10 MB 限制；为保留原图，不会自动压缩或转换')
  }
  return { file, wasCompressed: false, originalSize: file.size }
}
