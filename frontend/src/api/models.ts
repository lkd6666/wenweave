import { api } from './client'
import type { AIImageModelItem, AIModelItem } from '../types'

export const modelsApi = {
  list: () => api.get<AIModelItem[]>('/models'),
  listImage: () => api.get<AIImageModelItem[]>('/models/image'),
}
