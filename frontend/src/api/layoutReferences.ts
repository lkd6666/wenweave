import { api } from './client'
import type { LayoutCaptureSession, LayoutReferencePreview } from '../types'

export const layoutReferencesApi = {
  preview: (url: string) => api.post<LayoutReferencePreview>('/layout-references/preview', { url }),
  createCaptureSession: (url: string) => api.post<LayoutCaptureSession>('/layout-references/capture-sessions', { url }),
}
