import { api } from './client'
import type { TemplateCategory, TemplateGeneration, TemplateItem, TemplateSourceType } from '../types'

export interface TemplateWritePayload {
  name: string
  category_id: number | null
  html: string
  source_type: TemplateSourceType
}

export const templateLibraryApi = {
  listCategories: () => api.get<TemplateCategory[]>('/template-library/categories'),
  createCategory: (payload: { name: string; sort_order?: number }) => api.post<TemplateCategory>('/template-library/categories', payload),
  updateCategory: (categoryId: number, payload: { name: string; sort_order?: number }) =>
    api.patch<TemplateCategory>(`/template-library/categories/${categoryId}`, payload),
  deleteCategory: (categoryId: number) => api.delete<void>(`/template-library/categories/${categoryId}`),
  listTemplates: (params: { categoryId?: number; query?: string; sort?: 'updated' | 'name' } = {}) => {
    const search = new URLSearchParams()
    if (params.categoryId) search.set('category_id', String(params.categoryId))
    if (params.query?.trim()) search.set('q', params.query.trim())
    if (params.sort && params.sort !== 'updated') search.set('sort', params.sort)
    const suffix = search.size ? `?${search}` : ''
    return api.get<TemplateItem[]>(`/template-library/templates${suffix}`)
  },
  createTemplate: (payload: TemplateWritePayload) => api.post<TemplateItem>('/template-library/templates', payload),
  updateTemplate: (templateId: number, payload: TemplateWritePayload) =>
    api.patch<TemplateItem>(`/template-library/templates/${templateId}`, payload),
  deleteTemplate: (templateId: number) => api.delete<void>(`/template-library/templates/${templateId}`),
  createGeneration: (payload: { model_id: number; prompt: string }) =>
    api.post<TemplateGeneration>('/template-library/generations', payload),
  getGeneration: (generationId: string) => api.get<TemplateGeneration>(`/template-library/generations/${encodeURIComponent(generationId)}`),
  cancelGeneration: (generationId: string) => api.post<TemplateGeneration>(`/template-library/generations/${encodeURIComponent(generationId)}/cancel`, {}),
  saveGeneration: (generationId: string, payload: { name: string; category_id: number | null }) =>
    api.post<TemplateItem>(`/template-library/generations/${encodeURIComponent(generationId)}/save`, payload),
}
