import { api } from './client'
import type { LayoutCaptureSession, LayoutReferencePreview } from '../types'

export const layoutReferencesApi = {
  paste: (content: string, format: 'text' | 'html', title = '', downloadExternalImages = false) => api.post<LayoutReferencePreview>('/layout-references/paste', {
    content, format, title, download_external_images: downloadExternalImages,
  }),
  preview: (url: string) => api.post<LayoutReferencePreview>('/layout-references/preview', { url }),
  createCaptureSession: (url: string) => api.post<LayoutCaptureSession>('/layout-references/capture-sessions', { url }),
}
