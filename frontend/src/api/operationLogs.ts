import { api } from './client'
import type { OperationLog, OperationLogListResult, OperationLogStatus } from '../types'

export interface OperationLogQuery {
  page?: number
  page_size?: number
  actor_user_id?: number
  action?: string
  resource_type?: string
  document_id?: number
  status?: OperationLogStatus
  client_ip?: string
  started_at?: string
  ended_at?: string
  keyword?: string
}

function queryString(query: OperationLogQuery): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

export const operationLogsApi = {
  list: (query: OperationLogQuery = {}) => api.get<OperationLogListResult>(`/operation-logs${queryString(query)}`),
  get: (id: number) => api.get<OperationLog>(`/operation-logs/${id}`),
}
