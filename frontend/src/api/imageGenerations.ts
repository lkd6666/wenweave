import { api } from './client'
import type { ImageGenerationItem, SelectedElementContext } from '../types'

export interface ImageGenerationWorkspaceBlock {
  block_id: string
  tag: string
  path: string
  expected_hash: string
  text: string
}

export interface CreateImageGenerationPayload {
  model_id: number
  session_id?: number | null
  purpose?: 'cover' | 'body'
  operation?: 'generate' | 'edit'
  prompt: string
  quantity: number
  aspect_ratio: 'square' | 'portrait' | 'landscape'
  quality: string
  timeout_seconds?: number
  anchor_block_id?: string
  source_image_url?: string
  target_image_index?: number
  direct_insert?: boolean
}

export interface ApplyGeneratedImagePayload {
  target: 'cover' | 'body'
  revision?: string
  anchor_block_id?: string
  expected_hash?: string
  source_image_url?: string
  source_image_hash?: string
  target_image_index?: number
  alt?: string
}

export const imageGenerationsApi = {
  list: (documentId: number) => api.get<ImageGenerationItem[]>(`/documents/${documentId}/image-generations`),
  workspace: (documentId: number) => api.get<{ revision: string; blocks: ImageGenerationWorkspaceBlock[] }>(`/documents/${documentId}/image-generations/workspace`),
  resolveWorkspace: (documentId: number, selection: SelectedElementContext) => api.post<{
    revision: string
    status: 'exact' | 'relocated'
    reason: string
    block: ImageGenerationWorkspaceBlock
  }>(`/documents/${documentId}/image-generations/workspace/resolve`, selection),
  get: (documentId: number, generationId: string) => api.get<ImageGenerationItem>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}`),
  create: (documentId: number, payload: CreateImageGenerationPayload) => api.post<ImageGenerationItem>(`/documents/${documentId}/image-generations`, payload),
  cancel: (documentId: number, generationId: string) => api.post<ImageGenerationItem>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}/cancel`, {}),
  removeAsset: (documentId: number, generationId: string, assetId: string) => api.delete<void>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}/assets/${encodeURIComponent(assetId)}`),
  apply: (documentId: number, generationId: string, assetId: string, payload: ApplyGeneratedImagePayload) => api.post<ImageGenerationItem>(`/documents/${documentId}/image-generations/${encodeURIComponent(generationId)}/assets/${encodeURIComponent(assetId)}/apply`, payload),
}
