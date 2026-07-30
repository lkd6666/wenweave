import { api } from './client'
import type { AppBranding } from '../types'

export const brandingApi = {
  get: () => api.get<AppBranding>('/branding'),
  update: (systemName: string) => api.put<AppBranding>('/branding', { system_name: systemName }),
  upload: (kind: 'logo' | 'favicon', file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.upload<AppBranding>(`/branding/${kind}`, formData)
  },
  remove: (kind: 'logo' | 'favicon') => api.delete<AppBranding>(`/branding/assets/${kind}`),
}
