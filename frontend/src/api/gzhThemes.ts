import { api } from './client'
import type {
  GzhApplyMode,
  GzhThemeCreatePayload,
  GzhThemeGeneration,
  GzhThemeItem,
  GzhThemeManagerItem,
  GzhThemeManifest,
  GzhThemeProposal,
  GzhThemeReferenceAsset,
} from '../types'

export const gzhThemesApi = {
  list: (includeDrafts = false) => api.get<GzhThemeItem[]>(`/gzh-themes${includeDrafts ? '?include_drafts=true' : ''}`),
  preview: (themeKey: string) => api.get<{ html: string }>(`/gzh-themes/${encodeURIComponent(themeKey)}/preview`),
  manifest: (themeKey: string) => api.get<GzhThemeManifest>(`/gzh-themes/${encodeURIComponent(themeKey)}/manifest`),
  createCustomTheme: (payload: GzhThemeCreatePayload) => api.post<GzhThemeItem>('/gzh-themes', payload),
  publishCustomTheme: (themeId: number) => api.post<GzhThemeItem>(`/gzh-themes/${themeId}/publish`, {}),
  listManaged: () => api.get<GzhThemeManagerItem[]>('/gzh-theme-manager'),
  uploadReferenceAsset: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<GzhThemeReferenceAsset>('/gzh-theme-assets', form)
  },
  createGeneration: (payload: {
    model_id: number
    brief: string
    name_hint: string
    slug_hint: string
    accent_color: string
    scenarios: string[]
    reference_asset_ids: string[]
    theme_id?: number
  }) => api.post<GzhThemeGeneration>('/gzh-theme-generations', payload),
  getGeneration: (generationId: string) => api.get<GzhThemeGeneration>(`/gzh-theme-generations/${encodeURIComponent(generationId)}`),
  cancelGeneration: (generationId: string) => api.post<GzhThemeGeneration>(`/gzh-theme-generations/${encodeURIComponent(generationId)}/cancel`, {}),
  saveGeneration: (generationId: string, payload: {
    name: string
    slug: string
    description: string
    accent_color: string
    scenarios: string[]
  }) => api.post<GzhThemeManagerItem>(`/gzh-theme-generations/${encodeURIComponent(generationId)}/save`, payload),
  previewVersion: (versionId: number) => api.get<{ html: string }>(`/gzh-theme-versions/${versionId}/preview`),
  publishVersion: (versionId: number) => api.post<GzhThemeManagerItem>(`/gzh-theme-versions/${versionId}/publish`, {}),
  archiveTheme: (themeId: number) => api.post<GzhThemeManagerItem>(`/gzh-themes/${themeId}/archive`, {}),
  createProposal: (documentId: number, payload: {
    theme_key: string
    apply_mode: GzhApplyMode
    user_instructions: string
    article_type: string
    recipe_id: string
    selected_component_ids: string[]
    session_id: number | null
  }) => api.post<GzhThemeProposal>(`/documents/${documentId}/gzh-theme-proposals`, payload),
  approveProposal: (documentId: number, proposalId: string) =>
    api.post<GzhThemeProposal>(`/documents/${documentId}/gzh-theme-proposals/${proposalId}/approve`, {}),
}
