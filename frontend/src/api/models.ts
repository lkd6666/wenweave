import { api } from './client'
import type { AIModelItem } from '../types'

export const modelsApi = {
  list: () => api.get<AIModelItem[]>('/models'),
}
