export const STORAGE_PREVIEW_FETCH_LIMIT_BYTES = 50 * 1024 * 1024

export type StoragePreviewKind = 'image' | 'video' | 'pdf' | 'docx' | 'markdown' | 'text' | 'other'

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'])
const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'ogg'])

export function getStoragePreviewKind(filename: string): StoragePreviewKind {
  const extension = filename.trim().split('.').pop()?.toLowerCase() ?? ''
  if (IMAGE_EXTENSIONS.has(extension)) return 'image'
  if (VIDEO_EXTENSIONS.has(extension)) return 'video'
  if (extension === 'pdf') return 'pdf'
  if (extension === 'docx') return 'docx'
  if (extension === 'md') return 'markdown'
  if (extension === 'txt') return 'text'
  return 'other'
}

export function needsStoragePreviewFetch(kind: StoragePreviewKind): boolean {
  return kind === 'pdf' || kind === 'docx' || kind === 'markdown' || kind === 'text'
}
