import { api } from './client'
import type { ImageGenerationItem } from '../types'

export interface CreateImageGenerationPayload {
  model_id: number
  session_id?: number | null
  purpose: 'cover' | 'body'
  prompt: string
  quantity: number
  aspect_ratio: 'square' | 'portrait' | 'landscape'
  quality: string
  anchor_block_id?: string
  direct_insert?: boolean
}

export interface ApplyGeneratedImagePayload {
  target: 'cover' | 'body'
  revision?: string
  anchor_block_id?: string
  expected_hash?: string
  alt?: string
}

export const imageGenerationsApi = {
  list: (documentId: number) => api.get<ImageGenerationItem[]>(`/documents/${documentId}/image-generations`),
  workspace: (documentId: number) => api.get<{ revision: string; blocks: Array<{ block_id: string; expected_hash: string; text: string }> }>(`/documents/${documentId}/image-generations/workspace`),
  get: (documentId: number, generationId: string) => api.get<ImageGenerationItem>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}`),
  create: (documentId: number, payload: CreateImageGenerationPayload) => api.post<ImageGenerationItem>(`/documents/${documentId}/image-generations`, payload),
  cancel: (documentId: number, generationId: string) => api.post<ImageGenerationItem>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}/cancel`, {}),
  removeAsset: (documentId: number, generationId: string, assetId: string) => api.delete<void>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}/assets/${encodeURIComponent(assetId)}`),
  apply: (documentId: number, generationId: string, assetId: string, payload: ApplyGeneratedImagePayload) => api.post<ImageGenerationItem>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}/assets/${encodeURIComponent(assetId)}/apply`, payload),
}
