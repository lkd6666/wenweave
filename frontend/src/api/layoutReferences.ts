import { api } from './client'
import type { LayoutReferencePreview } from '../types'

export const layoutReferencesApi = {
  preview: (url: string) => api.post<LayoutReferencePreview>('/layout-references/preview', { url }),
}
