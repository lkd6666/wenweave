import { api } from './client'
import type { UploadOptions } from './client'
import type { ChatImageAttachment, ImageLibraryAsset, ImageLibraryListResult, ImageLibraryMode, ImageLibrarySource } from '../types'

export interface ImageLibrarySettings {
  mode: ImageLibraryMode
  updated_at: string | null
}

export const imageLibraryApi = {
  settings: () => api.get<ImageLibrarySettings>('/image-library/settings'),
  settingsAssets: () => api.get<ImageLibraryAsset[]>('/image-library/settings/assets'),
  updateSettings: (mode: ImageLibraryMode, sharedAssetIds: string[]) =>
    api.put<ImageLibrarySettings>('/image-library/settings', { mode, shared_asset_ids: sharedAssetIds }),
  list: (params: { q?: string; source?: 'all' | ImageLibrarySource; page?: number; page_size?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.q) query.set('q', params.q)
    if (params.source) query.set('source', params.source)
    if (params.page) query.set('page', String(params.page))
    if (params.page_size) query.set('page_size', String(params.page_size))
    return api.get<ImageLibraryListResult>(`/image-library/assets?${query.toString()}`)
  },
  upload: (documentId: number, files: File[], options?: UploadOptions) => {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    return api.upload<ImageLibraryAsset[]>(`/image-library/assets/upload?document_id=${documentId}`, formData, options)
  },
  importSearch: (documentId: number, candidateToken: string) =>
    api.post<ImageLibraryAsset>('/image-library/assets/import-search', { document_id: documentId, candidate_token: candidateToken }),
  rename: (assetId: string, name: string) =>
    api.patch<ImageLibraryAsset>(`/image-library/assets/${encodeURIComponent(assetId)}`, { name }),
  referenceChat: (assetId: string, documentId: number) =>
    api.post<ChatImageAttachment>(`/image-library/assets/${encodeURIComponent(assetId)}/chat-reference`, { document_id: documentId }),
  referenceChatMany: (assetIds: string[], documentId: number) =>
    api.post<ChatImageAttachment[]>('/image-library/assets/chat-references', { document_id: documentId, asset_ids: assetIds }),
  remove: (assetId: string) => api.delete<void>(`/image-library/assets/${encodeURIComponent(assetId)}`),
  removeMany: (assetIds: string[]) => api.post<void>('/image-library/assets/bulk-delete', { asset_ids: assetIds }),
  setCover: (assetId: string, documentId: number) =>
    api.post<ImageLibraryAsset>(`/image-library/assets/${encodeURIComponent(assetId)}/cover`, { document_id: documentId }),
}
