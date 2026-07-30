import { api } from './client'
import type { WorkboardData, WorkboardPeriod } from '../types'

export const workboardApi = {
  get: (period: WorkboardPeriod) => api.get<WorkboardData>(`/workboard?period=${period}`),
}
