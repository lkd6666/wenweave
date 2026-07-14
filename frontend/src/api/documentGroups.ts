import { api } from './client'
import type { DocumentGroup, VisibilitySettings } from '../types'

export type DocumentGroupUpdatePayload = { name?: string } & Partial<VisibilitySettings>

export const documentGroupsApi = {
  list: () => api.get<DocumentGroup[]>('/document-groups'),
  create: (name: string) => api.post<DocumentGroup>('/document-groups', { name }),
  update: (id: number, payload: string | DocumentGroupUpdatePayload) =>
    api.patch<DocumentGroup>(`/document-groups/${id}`, typeof payload === 'string' ? { name: payload } : payload),
  remove: (id: number) => api.delete<void>(`/document-groups/${id}`),
}
