import { api } from './client'
import type { ArticleTypographySettings } from '../types'

export type ArticleTypographySettingsUpdate = Omit<ArticleTypographySettings, 'updated_at'>

export const articleTypographyApi = {
  get: () => api.get<ArticleTypographySettings>('/article-typography-settings'),
  update: (payload: ArticleTypographySettingsUpdate) => api.put<ArticleTypographySettings>('/article-typography-settings', payload),
}
