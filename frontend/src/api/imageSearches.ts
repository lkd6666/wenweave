import { api } from './client'
import type { ImageSearchOrientation, ImageSearchResult } from '../types'

export interface SearchImagesPayload {
  query: string
  page?: number
  orientation?: ImageSearchOrientation
}

export interface ApplySearchedImagePayload {
  candidate_token: string
  target: 'cover' | 'body'
  revision?: string
  anchor_block_id?: string
  expected_hash?: string
  source_image_url?: string
  source_image_hash?: string
  target_image_index?: number
  alt?: string
}

export interface AppliedSearchedImage {
  ok: boolean
  target: 'cover' | 'body' | 'replace'
  url: string
  revision: string
}

export const imageSearchesApi = {
  search: (documentId: number, payload: SearchImagesPayload) =>
    api.post<ImageSearchResult>(`/documents/${documentId}/image-searches`, payload),
  apply: (documentId: number, payload: ApplySearchedImagePayload) =>
    api.post<AppliedSearchedImage>(`/documents/${documentId}/image-searches/apply`, payload),
}
